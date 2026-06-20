import time
from http import HTTPStatus

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.observability.audit import audit_log
from app.observability.metrics import record_request, status_class


SKIP_AUDIT_PATH_PREFIXES = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json", "/admin")


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            raise
        finally:
            request = Request(scope)
            duration_seconds = time.perf_counter() - start
            response_status_class = status_class(status_code)
            endpoint = self._classify_endpoint(request.url.path)
            provider = self._provider_context(request)

            record_request(provider, endpoint, response_status_class, duration_seconds)

            if not self._skip_audit(request.url.path):
                self._audit_request(request, provider, status_code, duration_seconds)

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
            if path:
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

    def _audit_request(self, request: Request, provider: str, status_code: int, duration_seconds: float) -> None:
        level = self._level_for_status(status_code)
        log = getattr(audit_log, level)
        log(
            "request_completed",
            client_id=request.headers.get("X-Client-ID", "anonymous"),
            method=request.method,
            path=self._route_pattern(request),
            provider=provider,
            params=dict(request.query_params),
            status_code=status_code,
            duration_ms=round(duration_seconds * 1000, 2),
        )

    @staticmethod
    def _level_for_status(status_code: int) -> str:
        if 400 <= status_code < 500:
            return "warning"
        if status_code >= 500:
            return "error"
        return "info"
