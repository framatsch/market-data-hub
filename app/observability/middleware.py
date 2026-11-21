import re
import time
from http import HTTPStatus
from typing import Any
from uuid import uuid4

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.audit import audit_log
from app.observability.metrics import (
    record_data_request,
    record_request,
    release_cache_misses,
    status_class,
)
from app.observability.telemetry import (
    RequestTelemetry,
    canonical_telemetry_symbol,
    request_telemetry,
)

SKIP_AUDIT_PATH_PREFIXES = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/admin",
    "/api/admin/auth",
)

_AUDIT_REDACTED_KEYS = {
    "value",
    "token_json",
    "api_key",
    "app_secret",
    "password",
}
_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_PROVIDER_ID = re.compile(r"[A-Za-z0-9._-]+(?:\+[A-Za-z0-9._-]+)*")


def request_id_for(request: Request) -> str:
    inbound = request.headers.get("X-Request-ID", "")
    return inbound if _REQUEST_ID.fullmatch(inbound) else uuid4().hex


def data_response_headers(telemetry: RequestTelemetry, status: int) -> dict[str, str]:
    headers = {"X-Request-ID": telemetry.request_id}
    if telemetry.endpoint_key() == "other":
        return headers
    timing = telemetry.finish(time.perf_counter())
    success = 200 <= status < 300 or status == 304
    if telemetry.data_provider and not _PROVIDER_ID.fullmatch(telemetry.data_provider):
        telemetry.data_provider = None
    headers["Server-Timing"] = timing.server_timing(telemetry, success)
    if success:
        headers["X-Data-Source"] = telemetry.source()
        headers["X-Data-Provider"] = telemetry.data_provider or "none"
    return headers


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
        completed = False
        request = Request(scope)
        telemetry = RequestTelemetry(
            request_id_for(request), "http", start=start, http_scope=scope
        )
        scope["mdh_telemetry"] = telemetry
        token = request_telemetry.set(telemetry)
        structlog.contextvars.bind_contextvars(request_id=telemetry.request_id)

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers.update(data_response_headers(telemetry, status_code))
                if status_code >= 400:
                    for name in ("X-Data-Source", "X-Data-Provider"):
                        if name in headers:
                            del headers[name]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            completed = True
        finally:
            try:
                duration_seconds = time.perf_counter() - start
                response_status_class = status_class(status_code)
                endpoint = self._classify_endpoint(request.url.path)
                provider = self._provider_context(request)

                record_request(
                    provider, endpoint, response_status_class, duration_seconds
                )
                if (
                    completed
                    and (200 <= status_code < 300 or status_code == 304)
                    and telemetry.response_timing is not None
                ):
                    record_data_request(telemetry, telemetry.response_timing.elapsed)

                if not self._skip_audit(request.url.path):
                    self._audit_request(
                        request, provider, status_code, duration_seconds
                    )
            finally:
                release_cache_misses(telemetry)
                telemetry.endpoint = telemetry.endpoint_key()
                telemetry.http_scope = None
                request_telemetry.reset(token)
                structlog.contextvars.clear_contextvars()

    @staticmethod
    def _classify_endpoint(path: str) -> str:
        if path.startswith("/prices"):
            return "prices"
        if path.startswith("/options"):
            return "options"
        if path.startswith("/companies"):
            if path.endswith("/news") or "/news" in path:
                return "news"
            return "companies"
        if path.startswith("/news"):
            return "news"
        if path.startswith("/health"):
            return "health"
        if path.startswith("/api/admin"):
            return "admin"
        if path.startswith("/admin"):
            return "admin"
        if path.startswith("/mcp"):
            return "mcp"
        if path.startswith("/metrics"):
            return "metrics"
        return "other"

    @staticmethod
    def _route_pattern(request: Request) -> str:
        route = request.scope.get("route")
        if route is not None:
            path = getattr(route, "path", None)
            if isinstance(path, str) and path:
                return path
        return request.url.path

    @staticmethod
    def _skip_audit(path: str) -> bool:
        return path.startswith(SKIP_AUDIT_PATH_PREFIXES)

    @staticmethod
    def _provider_context(request: Request) -> str:
        context = structlog.contextvars.get_contextvars()
        provider = context.get("provider")
        if isinstance(provider, str) and provider:
            return provider
        query_provider = request.query_params.get("provider")
        if query_provider:
            return query_provider.lower()
        return "none"

    def _audit_request(
        self, request: Request, provider: str, status_code: int, duration_seconds: float
    ) -> None:
        level = self._level_for_status(status_code)
        log = getattr(audit_log, level)
        telemetry: RequestTelemetry = request.scope["mdh_telemetry"]
        fields = {}
        if telemetry.endpoint_key() != "other":
            if telemetry.symbol is None:
                telemetry.symbol = canonical_telemetry_symbol(
                    request.path_params.get("symbol"),
                    request.query_params.get("sec_type"),
                )
            timing = telemetry.finish(time.perf_counter())
            fields = timing.log_fields(
                telemetry, 200 <= status_code < 300 or status_code == 304
            )
        log(
            "request_completed",
            request_id=telemetry.request_id,
            client_id=request.headers.get("X-Client-ID", "anonymous"),
            method=request.method,
            path=self._route_pattern(request),
            provider=provider,
            params=self._redact_params(request.query_params),
            status_code=status_code,
            duration_ms=round(duration_seconds * 1000, 2),
            **fields,
        )

    @staticmethod
    def _redact_params(query_params: Any) -> dict[str, str]:
        params = dict(query_params)
        for key in list(params):
            if key.lower() in _AUDIT_REDACTED_KEYS:
                params[key] = "[REDACTED]"
        return params

    @staticmethod
    def _level_for_status(status_code: int) -> str:
        if 400 <= status_code < 500:
            return "warning"
        if status_code >= 500:
            return "error"
        return "info"
