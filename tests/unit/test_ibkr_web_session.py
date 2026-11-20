import asyncio
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.config import settings
from app.providers.ibkr_web_config import IbkrWebConnectionConfig
from app.providers.ibkr_web_session import GatewayPacer, IbkrWebSession
from app.utils.errors import (
    DataNotFoundError,
    DataValidationError,
    ProviderConnectionError,
    ProviderError,
    ProviderNotAvailableError,
    ProviderTimeoutError,
)

FIXTURES = json.loads((Path(__file__).parents[1] / "fixtures/ibkrweb/gateway_responses.json").read_text())
STATUS = "/v1/api/iserver/auth/status"
INIT = "/v1/api/iserver/auth/ssodh/init"
ACCOUNTS = "/v1/api/iserver/accounts"
TICKLE = "/v1/api/tickle"
STOCKS = "/v1/api/trsrv/stocks"


class Clock:
    now = 0.0

    def time(self):
        return self.now

    async def sleep(self, delay):
        self.now += delay


@pytest.fixture
async def session_factory(monkeypatch):
    sessions = []
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "")

    def make(handler, *, clock=None, sleep=None, **config):
        clock = clock or Clock()
        session = IbkrWebSession(
            IbkrWebConnectionConfig(base_url="https://localhost:5000", verify_tls=False, **config),
            timeout=1,
            transport=httpx.MockTransport(handler),
            pacer=GatewayPacer(6, clock=clock.time, sleep=clock.sleep),
            sleep=sleep or clock.sleep,
        )
        sessions.append(session)
        return session

    yield make
    for session in sessions:
        await session.close()


@pytest.mark.parametrize("origin", ["https://localhost:5000/", "https://127.0.0.2:5000", "https://[::1]:5000", "https://ibkr-cpgw:5000"])
def test_insecure_tls_is_limited_to_local_gateways(origin):
    config = IbkrWebConnectionConfig(base_url=origin, verify_tls=False)
    assert config.verification() is False
    assert config.origin == origin.rstrip("/")


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5000", "https://10.0.0.5:5000", "https://localhost.example:5000", "https://localhost:0",
     "https://localhost:5000@remote.example", "https://localhost:5000/path", "https://localhost:5000/?secret=1"],
)
def test_insecure_tls_rejects_remote_or_malformed_origin(origin):
    with pytest.raises(ValidationError, match="verify_tls|base_url"):
        IbkrWebConnectionConfig(base_url=origin, verify_tls=False)


def test_remote_gateway_requires_certificate_verification():
    config = IbkrWebConnectionConfig(base_url="https://gateway.example", verify_tls=True)
    assert config.verification() is True


async def test_concurrent_initialization_is_serialized_and_cookies_are_retained(session_factory):
    clock = Clock()
    requests = []
    init_times = []

    async def handle(request):
        path = request.url.path
        requests.append(path)
        assert request.headers["user-agent"].startswith("market-data-hub/")
        if path == STATUS:
            assert request.method == "POST" and json.loads(request.content) == {}
            return httpx.Response(200, headers={"Set-Cookie": "gateway=test; Secure; Path=/"},
                                  json={**FIXTURES["status_ready"], "authenticated": False})
        assert request.headers["cookie"] == "gateway=test"
        if path == INIT:
            assert json.loads(request.content) == {"publish": True, "compete": False}
            init_times.append(clock.now)
            await asyncio.sleep(0)  # let the other callers contend for the init lock
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if path == ACCOUNTS:
            assert clock.now - init_times[0] == pytest.approx(2)
            return httpx.Response(200, json=FIXTURES["accounts"])
        assert path == STOCKS
        return httpx.Response(200, json=FIXTURES["stocks"])

    session = session_factory(handle, clock=clock, account_id="TEST2")
    assert await asyncio.gather(*(session.request("trsrv/stocks") for _ in range(5))) == [FIXTURES["stocks"]] * 5
    assert requests == [STATUS, INIT, ACCOUNTS, *([STOCKS] * 5)]
    assert session.status()["account_count"] == 1
    assert session.state == "ready"


async def test_unauthorized_stops_quotes_until_keep_alive_detects_login(session_factory):
    requests = []

    def handle(request):
        path = request.url.path
        requests.append(path)
        if path == STATUS:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        if path == TICKLE:
            return httpx.Response(200, json=FIXTURES["tickle"])
        return httpx.Response(401) if requests.count(STOCKS) == 1 else httpx.Response(200, json={})

    session = session_factory(handle)
    for _ in range(3):
        with pytest.raises(ProviderNotAvailableError) as error:
            await session.request("trsrv/stocks")
        assert error.value.details == {"reason": "login_required", "login_url": "https://localhost:5000"}
    assert requests == [STATUS, ACCOUNTS, STOCKS]
    await session.tickle()
    assert session.status()["last_tickle"]
    assert session.status()["sso_expires_seconds"] > 0
    assert await session.request("trsrv/stocks") == {}
    assert requests[-3:] == [TICKLE, ACCOUNTS, STOCKS]


async def test_competing_session_with_default_settings_does_not_attempt_init(session_factory):
    def handle(request):
        assert request.url.path == STATUS
        return httpx.Response(200, json={**FIXTURES["status_ready"], "competing": True, "authenticated": False})

    session = session_factory(handle)
    result = await session.test_connection()
    assert result["status_code"] == 409
    assert result["details"]["reason"] == "competing_session"
    assert session.state == "competing"


async def test_unreachable_gateway_returns_connection_error(session_factory):
    def handle(request):
        raise httpx.ConnectError("Connection refused", request=request)

    session = session_factory(handle)
    with pytest.raises(ProviderConnectionError, match="https://localhost:5000"):
        await session.request("trsrv/stocks")
    assert session.state == "unreachable"
    assert (await session.test_connection())["status_code"] == 503


async def test_ready_connection_test_is_bounded_even_when_no_accounts(session_factory):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path in {STATUS, INIT}:
            return httpx.Response(200, json={**FIXTURES["status_ready"], "authenticated": False})
        assert request.url.path == ACCOUNTS
        return httpx.Response(200, json={"accounts": []})

    result = await session_factory(handle).test_connection()
    assert result["status_code"] == 503
    assert result["details"]["state"] == "brokerage_pending"
    assert calls == [STATUS, INIT, ACCOUNTS]


async def test_gateway_reset_checks_status_and_reinitializes_before_next_quote(session_factory):
    calls = []

    def handle(request):
        path = request.url.path
        calls.append(path)
        if path == STATUS:
            return httpx.Response(200, json={**FIXTURES["status_ready"], "authenticated": calls.count(STATUS) == 1})
        if path == INIT:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        return (httpx.Response(503, json=FIXTURES["synthetic_errors"]["503"])
                if calls.count(STOCKS) == 1 else httpx.Response(200, json=FIXTURES["stocks"]))

    session = session_factory(handle)
    with pytest.raises(ProviderConnectionError, match="Service unavailable"):
        await session.request("trsrv/stocks")
    assert await session.request("trsrv/stocks") == FIXTURES["stocks"]
    assert calls == [STATUS, ACCOUNTS, STOCKS, STATUS, INIT, ACCOUNTS, STOCKS]


async def test_tickle_reinitializes_after_reset(session_factory):
    calls = []

    def handle(request):
        path = request.url.path
        calls.append(path)
        if path == TICKLE:
            auth = {**FIXTURES["status_ready"], "authenticated": False}
            return httpx.Response(200, json={"iserver": {"authStatus": auth}})
        if path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        return httpx.Response(200, json=FIXTURES["status_ready"])

    session = session_factory(handle)
    await session.ensure_ready()
    await session.tickle()
    assert calls == [STATUS, ACCOUNTS, TICKLE, INIT, ACCOUNTS]
    assert session.state == "ready"


async def test_waits_for_nonempty_brokerage_accounts(session_factory):
    accounts_attempts = 0

    def handle(request):
        nonlocal accounts_attempts
        if request.url.path == STATUS:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        assert request.url.path == ACCOUNTS
        accounts_attempts += 1
        body = {"accounts": []} if accounts_attempts == 1 else FIXTURES["accounts"]
        return httpx.Response(200, json=body)

    session = session_factory(handle)
    await session.ensure_ready()
    assert accounts_attempts == 2
    assert session.state == "ready"


async def test_login_alert_fires_only_once_per_transition(session_factory, monkeypatch):
    alerts = []
    logged_in = False

    def handle(request):
        if request.url.path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        if not logged_in:
            return httpx.Response(401)
        assert request.url.path == TICKLE
        return httpx.Response(200, json=FIXTURES["tickle"])

    async def send_alert(self, url):
        alerts.append(url)

    session = session_factory(handle)
    monkeypatch.setattr(IbkrWebSession, "_send_alert", send_alert)
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "https://webhook.example")
    for _ in range(2):
        with pytest.raises(ProviderNotAvailableError):
            await session.tickle()
    await asyncio.sleep(0)
    assert len(alerts) == 1
    logged_in = True
    await session.tickle()
    logged_in = False
    with pytest.raises(ProviderNotAvailableError):
        await session.tickle()
    await asyncio.sleep(0)
    assert len(alerts) == 2


async def test_keep_alive_is_cancelled_on_close(session_factory):
    sleeping = asyncio.Event()
    cancelled = asyncio.Event()

    async def sleep(_delay):
        sleeping.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    def handle(_request):
        pytest.fail("Unexpected gateway request")

    session = session_factory(handle, sleep=sleep)
    session.start()
    await asyncio.wait_for(sleeping.wait(), timeout=1)
    await session.close()
    assert cancelled.is_set()
    with pytest.raises(ProviderNotAvailableError, match="ibkrweb"):
        await session.request("trsrv/stocks")


async def test_global_and_endpoint_limits():
    clock = Clock()
    pacer = GatewayPacer(6, clock=clock.time, sleep=clock.sleep)
    first_slots = []
    for _ in range(7):
        await pacer.acquire("iserver/marketdata/snapshot")
        first_slots.append(clock.now)
    assert first_slots[5] < 1 and first_slots[6] == pytest.approx(1)
    for _ in range(50):
        await pacer.acquire("iserver/marketdata/history")
    assert clock.now < 60
    await pacer.acquire("iserver/marketdata/history")
    assert clock.now >= 60

    for path, min_spacing in [("tickle", 1), ("sso/validate", 60)]:
        await pacer.acquire(path)
        previous = clock.now
        await pacer.acquire(path)
        assert clock.now - previous == pytest.approx(min_spacing)


async def test_penalty_prevents_data_and_keep_alive_requests(session_factory, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(settings, "IBKRWEB_PENALTY_SECONDS", 900)
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == STATUS:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if request.url.path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        return httpx.Response(429) if calls.count(STOCKS) == 1 else httpx.Response(200, json={})

    session = session_factory(handle, clock=clock)
    with pytest.raises(ProviderTimeoutError) as error:
        await session.request("trsrv/stocks")
    assert error.value.details == {"reason": "rate_limited", "retry_after_seconds": 900}
    with pytest.raises(ProviderTimeoutError):
        await session.tickle()
    assert (await session.test_connection())["status_code"] == 429
    assert session.status()["rate_limit_count"] == 1
    assert calls == [STATUS, ACCOUNTS, STOCKS]
    clock.now += 900
    assert await session.request("trsrv/stocks") == {}
    assert session.state == "ready"


@pytest.mark.parametrize(("code", "error"), [(200, ProviderError), (400, DataValidationError), (404, DataNotFoundError)])
async def test_bad_upstream_responses_do_not_become_empty_data(session_factory, code, error):
    def handle(request):
        if request.url.path == STATUS:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if request.url.path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        if code == 400:
            return httpx.Response(code, json=FIXTURES["error_400"])
        return httpx.Response(code, text="<html>Gateway error</html>")

    with pytest.raises(error):
        await session_factory(handle).request("trsrv/stocks")


def ready_handler(calls, data):
    def handle(request):
        path = request.url.path
        calls.append(path)
        if path == STATUS:
            return httpx.Response(200, json=FIXTURES["status_ready"])
        if path == ACCOUNTS:
            return httpx.Response(200, json=FIXTURES["accounts"])
        return data(path)
    return handle


async def test_data_5xx_keeps_session_ready_and_rechecks_once(session_factory):
    calls = []
    failures = {"left": 1}

    def data(_path):
        if failures["left"]:
            failures["left"] -= 1
            return httpx.Response(500, json={"error": "Chart data unavailable"})
        return httpx.Response(200, json=FIXTURES["stocks"])

    session = session_factory(ready_handler(calls, data))
    await session.ensure_ready()
    generation = session.generation
    with pytest.raises(ProviderConnectionError, match="Chart data unavailable"):
        await session.request("trsrv/stocks")
    # A routine 5xx must not fail requests that are already past the readiness check.
    assert session.state == "ready"
    results = await asyncio.gather(*(session.request("trsrv/stocks") for _ in range(3)))
    assert results == [FIXTURES["stocks"]] * 3
    # Exactly one status re-check, no re-initialisation and no stream reset (generation unchanged).
    assert calls.count(STATUS) == 2 and INIT not in calls
    assert session.generation == generation


async def test_failed_refresh_is_shared_by_queued_requests(session_factory):
    attempts = 0

    async def handle(request):
        nonlocal attempts
        attempts += 1
        await asyncio.sleep(0.01)  # like network I/O: the other requests queue on the session lock
        raise httpx.ConnectError("refused", request=request)

    session = session_factory(handle)
    results = await asyncio.gather(*(session.ensure_ready() for _ in range(5)), return_exceptions=True)
    assert all(isinstance(result, ProviderConnectionError) for result in results)
    assert attempts == 1
    # A later request probes again instead of replaying the old failure.
    with pytest.raises(ProviderConnectionError):
        await session.ensure_ready()
    assert attempts == 2


async def test_penalty_survives_session_replacement(monkeypatch):
    from app.providers import ibkr_web_session

    monkeypatch.setattr(ibkr_web_session, "_SHARED_PENALTIES", {})
    monkeypatch.setattr(settings, "IBKRWEB_PENALTY_SECONDS", 900)
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "")
    calls = []
    handle = ready_handler(calls, lambda _path: httpx.Response(429))
    config = IbkrWebConnectionConfig(base_url="https://localhost:5000", verify_tls=False)
    first = IbkrWebSession(config, timeout=1, transport=httpx.MockTransport(handle))
    with pytest.raises(ProviderTimeoutError):
        await first.request("trsrv/stocks")
    await first.close()
    second = IbkrWebSession(config, timeout=1, rate=2, transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(ProviderTimeoutError) as error:
            await second.request("trsrv/stocks")
        assert error.value.details["reason"] == "rate_limited"
        assert second.state == "rate_limited"
        assert calls == [STATUS, ACCOUNTS, "/v1/api/trsrv/stocks"]
    finally:
        await second.close()


async def test_keep_alive_survives_unexpected_errors(session_factory, monkeypatch):
    ticks = 0
    done = asyncio.Event()

    async def tickle(self):
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            raise RuntimeError("boom")
        done.set()

    async def sleep(_delay):
        await asyncio.sleep(0)

    monkeypatch.setattr(IbkrWebSession, "tickle", tickle)
    session = session_factory(lambda _request: pytest.fail("unexpected request"), sleep=sleep)
    session.start()
    await asyncio.wait_for(done.wait(), timeout=1)
    assert not session._keep_alive.done()
    assert session.status()["last_error"] == "Keep-alive failed: RuntimeError"


async def test_admin_logout_does_not_send_login_alert(session_factory, monkeypatch):
    alerts = []

    async def send_alert(self, url):
        alerts.append(url)

    monkeypatch.setattr(IbkrWebSession, "_send_alert", send_alert)
    monkeypatch.setattr(settings, "IBKRWEB_ALERT_WEBHOOK_URL", "https://webhook.example")
    calls = []
    session = session_factory(ready_handler(calls, lambda _path: httpx.Response(200, json={})))
    await session.ensure_ready()
    assert (await session.logout())["state"] == "login_required"
    await asyncio.sleep(0)
    assert alerts == []


def test_login_url_is_reported_for_login_required():
    config = IbkrWebConnectionConfig(
        base_url="https://ibkr-cpgw:5000", verify_tls=False, login_url="https://localhost:5000",
    )
    assert config.browser_login_url == "https://localhost:5000"
    assert IbkrWebConnectionConfig(base_url="https://localhost:5000", verify_tls=False).browser_login_url == "https://localhost:5000"
    for invalid in ("http://localhost:5000", "https://user@localhost:5000", "localhost:5000"):
        with pytest.raises(ValidationError, match="login_url"):
            IbkrWebConnectionConfig(base_url="https://localhost:5000", verify_tls=False, login_url=invalid)


async def test_hung_gateway_leaves_ready_after_repeated_tickle_timeouts(session_factory):
    calls = []
    base = ready_handler(calls, lambda _path: pytest.fail("no data request expected"))

    def handle(request):
        if request.url.path == TICKLE:
            calls.append(TICKLE)
            raise httpx.ReadTimeout("hung", request=request)
        return base(request)

    ticks = 0

    async def sleep(_delay):
        nonlocal ticks
        ticks += 1
        if ticks > 2:
            raise asyncio.CancelledError

    session = session_factory(handle, sleep=sleep)
    await session.ensure_ready()
    with pytest.raises(asyncio.CancelledError):
        await session._run_keep_alive()
    assert calls.count(TICKLE) == 2
    assert session.state == "unreachable"
    assert "keep-alive" in session.status()["last_error"]


async def test_login_alert_payload_and_failure_only_logged(session_factory, monkeypatch, caplog):
    from app.providers import ibkr_web_session

    sent = []

    def webhook(request):
        sent.append(json.loads(request.content))
        return httpx.Response(500 if len(sent) > 1 else 200)

    session = session_factory(lambda _request: httpx.Response(401), login_url="https://localhost:5443")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(ibkr_web_session, "validate_webhook_url", lambda _url: None)
    monkeypatch.setattr(
        ibkr_web_session.httpx, "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(webhook), **kwargs),
    )
    await session._send_alert("https://hooks.example/abc")
    assert sent == [{"text": "IBKR Client Portal Gateway login required — log in at https://localhost:5443"}]
    await session._send_alert("https://hooks.example/abc")  # HTTP 500 from the webhook
    assert "login alert failed" in caplog.text


async def test_session_gauge_follows_the_active_session(session_factory):
    from app.observability.metrics import PROVIDER_SESSION_STATE

    def gauge(state):
        return PROVIDER_SESSION_STATE.labels("ibkrweb", state)._value.get()

    calls = []
    first = session_factory(ready_handler(calls, lambda _path: httpx.Response(200, json={})))
    await first.ensure_ready()
    assert (gauge("ready"), gauge("unknown")) == (1, 0)
    second = session_factory(lambda request: httpx.Response(401))
    second.start()
    await first.close()  # the replaced session must not reset the successor's gauge
    assert (gauge("unknown"), gauge("ready")) == (1, 0)
    await second.close()
    assert gauge("unknown") == 0
