"""HTTP transport, session lifecycle and pacing for the IBKR Client Portal Gateway."""

import asyncio
import math
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from app.config import APP_VERSION, settings
from app.observability.metrics import (
    PROVIDER_RATE_LIMITS,
    PROVIDER_SESSION_STATE,
    UPSTREAM_REQUESTS,
)
from app.providers.ibkr_web_config import IbkrWebConnectionConfig
from app.utils.errors import (
    AppError,
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
    ProviderNotAvailableError,
    ProviderTimeoutError,
)
from app.utils.logging import logger
from app.utils.webhooks import validate_webhook_url

PROVIDER = "ibkrweb"
AUTH_STATUS = "iserver/auth/status"
INIT = "iserver/auth/ssodh/init"
ACCOUNTS = "iserver/accounts"
TICKLE = "tickle"
_COMPETING_HINT = "Another IBKR session of this username holds the brokerage session"
_RELATIVE_API_PATH = re.compile(r"[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*")
_SESSION_STATES = (
    "unknown", "unreachable", "login_required", "competing", "brokerage_pending", "ready", "rate_limited",
)
SessionState = Literal["unknown", "unreachable", "login_required", "competing", "brokerage_pending", "ready"]
_Payload = dict[str, Any] | list[Any]


# 429 penalties belong to the gateway, not to a provider instance that the registry may replace.
_SHARED_PENALTIES: dict[str, float] = {}
# Only the newest session may write the state gauge; a closed predecessor must not reset it.
_gauge_owner: "IbkrWebSession | None" = None
_RECHECK_INTERVAL_SECONDS = 30.0
_HUNG_TICKLES = 2  # consecutive keep-alive timeouts before the gateway counts as unreachable


class GatewayPacer:
    """A one-token bucket prevents bursts, with tighter per-endpoint windows."""

    _LIMITS = {
        "iserver/marketdata/history": (50, 60.0),
        TICKLE: (1, 1.0),
        "sso/validate": (1, 60.0),
    }

    def __init__(
        self,
        rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        penalty_key: str | None = None,
    ) -> None:
        if not 0 < rate <= 10:
            raise ValueError("ibkrweb rate_limit_per_sec must be greater than 0 and at most 10")
        self._clock = clock
        self._sleep = sleep
        self._spacing = 1 / rate
        self._next = -math.inf
        self._penalty_key = penalty_key
        self._penalty_until = _SHARED_PENALTIES.get(penalty_key, -math.inf) if penalty_key else -math.inf
        self._windows: dict[str, deque[float]] = {path: deque() for path in self._LIMITS}

    @property
    def retry_after_seconds(self) -> int:
        remaining = self._penalty_until - self._clock()
        return math.ceil(remaining) if remaining > 0 else 0

    def check_penalty(self) -> None:
        if remaining := self.retry_after_seconds:
            raise ProviderTimeoutError(PROVIDER, {"reason": "rate_limited", "retry_after_seconds": remaining})

    def penalize(self, seconds: float) -> None:
        self._penalty_until = max(self._penalty_until, self._clock() + seconds)
        if self._penalty_key:
            _SHARED_PENALTIES[self._penalty_key] = self._penalty_until

    async def acquire(self, path: str) -> None:
        # No await between checking and recording a slot: allocation is atomic on the event loop.
        window = self._windows.get(path)
        while True:
            self.check_penalty()
            now = self._clock()
            available_at = self._next
            if window is not None:
                limit, interval = self._LIMITS[path]
                while window and window[0] + interval <= now:
                    window.popleft()
                if len(window) >= limit:
                    available_at = max(available_at, window[0] + interval)
            if available_at <= now:
                self._next = now + self._spacing
                if window is not None:
                    window.append(now)
                return
            await self._sleep(available_at - now)


class IbkrWebSession:
    def __init__(
        self,
        config: IbkrWebConnectionConfig,
        *,
        timeout: float,
        rate: float = 6.0,
        transport: httpx.AsyncBaseTransport | None = None,
        pacer: GatewayPacer | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._pacer = pacer or GatewayPacer(rate, penalty_key=config.origin)
        self._client = httpx.AsyncClient(
            base_url=f"{config.origin}/v1/api/",
            verify=config.verification(),
            timeout=timeout,
            headers={"User-Agent": f"market-data-hub/{APP_VERSION}"},
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._lock = asyncio.Lock()
        self._state: SessionState = "unknown"
        self._metrics_state: str | None = None
        self._auth: dict[str, bool] = {}
        self._account_count = 0
        self._server_version: str | None = None
        self._last_tickle: datetime | None = None
        self._last_error: str | None = None
        self._expires_at: float | None = None
        self._rate_limit_count = 0
        self.generation = 0
        self._sso_checked_at = -math.inf
        self._username: str | None = None
        self._account_mode: str | None = None
        self._keep_alive: asyncio.Task[None] | None = None
        self._alerts: set[asyncio.Task[None]] = set()
        self._closed = False
        self._recheck_due = False
        self._last_recheck = -math.inf
        self._refresh_failure: tuple[float, AppError] | None = None
        self._keep_alive_error: str | None = None
        self._tickle_timeouts = 0

    @property
    def state(self) -> str:
        return "rate_limited" if self._pacer.retry_after_seconds else self._state

    def status(self) -> dict[str, Any]:
        return {
            "base_url": self.config.origin,
            "login_url": self.config.browser_login_url,
            "state": self.state,
            **{key: self._auth.get(key, False) for key in ("authenticated", "connected", "competing")},
            "server_version": self._server_version,
            "account_count": self._account_count,
            "username": self._username,
            "account_mode": self._account_mode,
            "sso_expires_seconds": (
                max(0, math.ceil(self._expires_at - time.monotonic())) if self._expires_at is not None else None
            ),
            "last_tickle": self._last_tickle.isoformat() if self._last_tickle else None,
            "last_error": self._last_error,
            "retry_after_seconds": self._pacer.retry_after_seconds,
            "rate_limit_count": self._rate_limit_count,
        }

    def start(self) -> None:
        if not self._closed and self._keep_alive is None:
            self._publish_state()
            self._keep_alive = asyncio.create_task(self._run_keep_alive(), name="ibkrweb-keep-alive")

    async def close(self) -> None:
        self._closed = True
        tasks = [*self._alerts]
        if self._keep_alive is not None:
            tasks.append(self._keep_alive)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._client.aclose()
        global _gauge_owner
        if _gauge_owner is self:
            _gauge_owner = None
            for label in _SESSION_STATES:
                PROVIDER_SESSION_STATE.labels(PROVIDER, label).set(0)

    async def request(
        self, path: str, *, params: Mapping[str, Any] | None = None,
        expected: type | tuple[type, ...] = dict,
    ) -> Any:
        """Send a read-only data request without retrying an upstream failure."""
        await self.ensure_ready()
        result = await self._send(path, params=params, require_ready=True)
        if not isinstance(result, expected):
            raise ProviderError("Unexpected IBKR Web API response shape", details={"endpoint": path})
        return result

    async def ensure_ready(self) -> None:
        self._pacer.check_penalty()
        if self._state == "ready" and not self._recheck_due:
            return
        waiting_since = time.monotonic()
        async with self._lock:
            self._pacer.check_penalty()
            if self._state in {"login_required", "competing"}:
                raise self._not_available()
            failure = self._refresh_failure
            if failure is not None and failure[0] >= waiting_since:
                # Another request just failed to refresh while this one waited: share that result.
                raise failure[1]
            if self._state == "ready" and not self._recheck_due:
                return
            self._recheck_due = False
            try:
                await self._refresh()
            except AppError as exc:
                self._refresh_failure = (time.monotonic(), exc)
                raise
            self._refresh_failure = None

    async def refresh(self) -> dict[str, Any]:
        """Explicitly re-check the gateway, even if the last request required login."""
        async with self._lock:
            await self._refresh()
        return self.status()

    async def admin_status(self) -> dict[str, Any]:
        if self.state == "ready" and time.monotonic() >= self._sso_checked_at + 60:
            async with self._lock:
                if self.state == "ready" and time.monotonic() >= self._sso_checked_at + 60:
                    self._sso_checked_at = time.monotonic()
                    try:
                        details = await self._session_json("sso/validate")
                    except AppError as exc:
                        self._last_error = exc.message
                    else:
                        username = details.get("USER_NAME")
                        self._username = username if isinstance(username, str) else None
                        login_type = details.get("LOGIN_TYPE")
                        self._account_mode = "live" if login_type == 1 else "paper" if login_type == 2 else None
        return self.status()

    async def logout(self) -> dict[str, Any]:
        """Explicit admin action; the shared gateway session is ended upstream."""
        async with self._lock:
            try:
                await self._send("logout", post={})
            except ProviderNotAvailableError as exc:
                if exc.details.get("reason") != "login_required":
                    raise
            self._client.cookies.clear()
            self._set_state("login_required", "Logged out by an administrator", alert=False)
            return self.status()

    async def test_connection(self) -> dict[str, Any]:
        async with self._lock:
            try:
                await self._refresh(accounts_once=True)
            except AppError as exc:
                reason = exc.details.get("reason", "")
                by_reason = {
                    "login_required": (401, "Login required at the Client Portal Gateway"),
                    "competing_session": (409, _COMPETING_HINT),
                    "rate_limited": (429, "IBKR Web API is rate limited"),
                }
                status_code, message = by_reason.get(reason, (503, "Client Portal Gateway not reachable" if self._state == "unreachable" else exc.message))
                return {"status_code": status_code, "success": False, "message": message,
                        "details": {**self.status(), **exc.details, "error": exc.message}}
        return {"status_code": 200, "success": True, "message": "Connected to IBKR Web API",
                "details": self.status()}

    async def tickle(self) -> None:
        async with self._lock:
            body = await self._session_json(TICKLE, post={})
            self._last_tickle = datetime.now(UTC)
            expires_ms = body.get("ssoExpires")
            if (
                isinstance(expires_ms, (int, float))
                and not isinstance(expires_ms, bool)
                and math.isfinite(expires_ms)
            ):
                self._expires_at = time.monotonic() + max(0, expires_ms) / 1000
            iserver = body.get("iserver")
            auth = iserver.get("authStatus") if isinstance(iserver, dict) else None
            if not isinstance(auth, dict):
                raise ProviderError("Missing IBKR Web API tickle auth status")
            await self._apply_auth(auth)

    async def _run_keep_alive(self) -> None:
        while True:
            await self._sleep(settings.IBKRWEB_TICKLE_INTERVAL_SECONDS)
            try:
                await self.tickle()
            except asyncio.CancelledError:
                raise
            except ProviderTimeoutError as exc:
                if exc.details.get("reason") == "rate_limited":
                    continue
                self._tickle_timeouts += 1
                if self._tickle_timeouts >= _HUNG_TICKLES and self._state == "ready":
                    # The next request re-checks the session instead of trusting a stale "ready".
                    self._set_state("unreachable", "Client Portal Gateway did not answer the keep-alive")
                self._log_keep_alive_failure(exc.message)
            except AppError as exc:
                self._last_error = exc.message
                self._log_keep_alive_failure(exc.message)
            except Exception as exc:  # the task must survive anything a single tickle raises
                self._last_error = f"Keep-alive failed: {type(exc).__name__}"
                self._log_keep_alive_failure(self._last_error, unexpected=True)
            else:
                self._tickle_timeouts = 0
                if self._keep_alive_error is not None:
                    logger.info("IBKR Web API keep-alive recovered")
                self._keep_alive_error = None

    def _log_keep_alive_failure(self, message: str, *, unexpected: bool = False) -> None:
        # One line per distinct failure; state transitions are logged separately.
        if message == self._keep_alive_error:
            return
        self._keep_alive_error = message
        if unexpected:
            logger.exception("IBKR Web API keep-alive error: %s", message)
        else:
            logger.warning("IBKR Web API keep-alive failed: %s", message)

    async def _refresh(self, *, accounts_once: bool = False) -> None:
        auth = await self._session_json(AUTH_STATUS, post={})
        await self._apply_auth(auth, accounts_once=accounts_once)

    async def _apply_auth(self, auth: dict[str, Any], *, accounts_once: bool = False) -> None:
        if not all(type(auth.get(key)) is bool for key in ("connected", "authenticated", "competing")):
            raise ProviderError("Invalid IBKR Web API auth status")
        self._auth = {key: auth[key] for key in ("connected", "authenticated", "competing")}
        info = auth.get("serverInfo")
        if isinstance(info, dict) and isinstance(info.get("serverVersion"), str):
            self._server_version = info["serverVersion"]
        if auth["competing"] and not self.config.compete:
            self._set_state("competing", _COMPETING_HINT)
            raise self._not_available()
        if not auth["connected"]:
            self._set_state("login_required", "Login required at the Client Portal Gateway")
            raise self._not_available()
        init_required = not auth["authenticated"] or auth["competing"]
        if not init_required and self._state == "ready" and not accounts_once:
            return
        renew = init_required or self._state != "ready"
        if renew:
            self._set_state("brokerage_pending")
        try:
            async with asyncio.timeout(settings.IBKRWEB_SESSION_INIT_TIMEOUT_SECONDS):
                if init_required:
                    await self._session_json(INIT, post={"publish": True, "compete": self.config.compete})
                    await self._sleep(2)
                await self._load_accounts(once=accounts_once)
        except TimeoutError as exc:
            self._last_error = "IBKR Web API brokerage initialisation timed out"
            raise ProviderTimeoutError(PROVIDER, {"reason": "session_init_timeout"}) from exc
        self._auth.update(authenticated=True, competing=False)
        if renew:
            self.generation += 1
        self._set_state("ready")

    async def _load_accounts(self, *, once: bool) -> None:
        while True:
            body = await self._session_json(ACCOUNTS)
            accounts = body.get("accounts")
            if not isinstance(accounts, list) or not all(isinstance(value, str) for value in accounts):
                raise ProviderError("Invalid IBKR Web API accounts payload")
            if accounts:
                self._account_count = len(accounts)
                if self.config.account_id and self.config.account_id not in accounts:
                    logger.warning("IBKR Web API account_id is not in the brokerage session account list")
                return
            if once:
                self._set_state("brokerage_pending", "No brokerage accounts returned by the gateway")
                raise self._not_available()
            await self._sleep(0.5)

    async def _session_json(self, path: str, *, post: dict[str, Any] | None = None) -> dict[str, Any]:
        body = await self._send(path, post=post)
        if not isinstance(body, dict):
            raise ProviderError("Unexpected IBKR Web API session response shape", details={"endpoint": path})
        return body

    async def _send(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        post: dict[str, Any] | None = None,
        require_ready: bool = False,
    ) -> _Payload:
        if not _RELATIVE_API_PATH.fullmatch(path):
            raise ValueError("Gateway endpoint must be a relative API path")
        if self._closed:
            raise ProviderNotAvailableError(PROVIDER, {"reason": "session_closed"})
        await self._pacer.acquire(path)
        if self._closed:
            raise ProviderNotAvailableError(PROVIDER, {"reason": "session_closed"})
        if require_ready and self._state != "ready":
            raise self._not_available()
        self._publish_state()
        UPSTREAM_REQUESTS.labels(PROVIDER).inc()
        try:
            if post is None:
                response = await self._client.get(path, params=params)
            else:
                response = await self._client.post(path, json=post)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER, {"endpoint": path}) from exc
        except httpx.RequestError as exc:
            message = f"Client Portal Gateway not reachable at {self.config.origin}"
            self._set_state("unreachable", message)
            raise ProviderConnectionError(message) from exc
        code = response.status_code
        if code == 429:
            self._rate_limit_count += 1
            PROVIDER_RATE_LIMITS.labels(PROVIDER).inc()
            self._pacer.penalize(settings.IBKRWEB_PENALTY_SECONDS)
            self._publish_state()
            self._pacer.check_penalty()
        if code == 401:
            self._set_state("login_required", "Login required at the Client Portal Gateway")
            raise self._not_available()
        body: Any = None
        with suppress(ValueError):
            body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        message = error[:500] if isinstance(error, str) else f"Gateway returned HTTP {code}"
        if code == 400:
            raise DataValidationError(message)
        if code == 404:
            raise DataNotFoundError("IBKR Web API resource", path)
        if code in {500, 503}:
            # A 5xx may be the nightly IServer reset or an ordinary per-request failure. Keep the
            # session usable for requests in flight and re-check the status before the next one.
            now = time.monotonic()
            if self._state == "ready" and now >= self._last_recheck + _RECHECK_INTERVAL_SECONDS:
                self._last_recheck = now
                self._recheck_due = True
            raise ProviderConnectionError(message)
        if not response.is_success or not isinstance(body, (dict, list)):
            raise ProviderError("Unexpected IBKR Web API response", details={"endpoint": path, "status": code})
        return body

    def _not_available(self) -> ProviderNotAvailableError:
        if self._state == "login_required":
            return ProviderNotAvailableError(PROVIDER, {"reason": "login_required", "login_url": self.config.browser_login_url})
        if self._state == "competing":
            return ProviderNotAvailableError(PROVIDER, {"reason": "competing_session", "hint": _COMPETING_HINT})
        return ProviderNotAvailableError(PROVIDER, {"reason": "brokerage_pending"})

    def _set_state(self, state: SessionState, error: str | None = None, *, alert: bool = True) -> None:
        previous = self._state
        self._state, self._last_error = state, error
        if state != "ready":
            self._account_count = 0
        if state in {"unreachable", "login_required"}:
            self._auth = {}
            self._expires_at = None
            self._username = None
            self._account_mode = None
        self._publish_state()
        if (
            state == "login_required" and previous != state and alert
            and settings.IBKRWEB_ALERT_WEBHOOK_URL and not self._closed
        ):
            task = asyncio.create_task(self._send_alert(settings.IBKRWEB_ALERT_WEBHOOK_URL))
            self._alerts.add(task)
            task.add_done_callback(self._alerts.discard)

    def _publish_state(self) -> None:
        global _gauge_owner
        if self._closed:
            return  # a replaced session must not overwrite the gauge of its successor
        state = self.state
        if state == self._metrics_state and _gauge_owner is self:
            return
        _gauge_owner = self
        previous = self._metrics_state or "unknown"
        if state != previous:
            level = (
                logger.warning
                if previous == "ready" or state in {"login_required", "rate_limited"}
                else logger.info
            )
            level("IBKR Web API session: %s → %s", previous, state)
        self._metrics_state = state
        for label in _SESSION_STATES:
            PROVIDER_SESSION_STATE.labels(PROVIDER, label).set(int(label == state))

    async def _send_alert(self, webhook_url: str) -> None:
        try:
            await asyncio.to_thread(validate_webhook_url, webhook_url)
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                response = await client.post(webhook_url, json={
                    "text": f"IBKR Client Portal Gateway login required — log in at {self.config.browser_login_url}",
                })
                response.raise_for_status()
        except (ValueError, httpx.HTTPError) as exc:
            logger.warning("IBKR Web API login alert failed (%s)", type(exc).__name__)
