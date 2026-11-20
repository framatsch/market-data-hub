"""Per-request response metadata collected by services and read by routes.

Services record when and how the data was obtained (`data_as_of`, stale markers);
routes put it into `ResponseEnvelope.meta`. The state is bound to the request by
the `cache` decorator, so it works for HTTP routes and is harmless elsewhere.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.observability.telemetry import current_telemetry


@dataclass
class ResponseMeta:
    data_as_of: datetime | None = None
    stale: bool = False
    stale_reason: str | None = None
    source_provider: str | None = None
    no_cache: bool = False

    def record_fetch(self, fetched_at: datetime | None = None) -> None:
        """Record the time of a provider call; the oldest data wins."""
        moment = fetched_at or datetime.now(UTC)
        if self.data_as_of is None or moment < self.data_as_of:
            self.data_as_of = moment

    def mark_stale(self, reason: str, source_provider: str | None = None) -> None:
        self.stale = True
        self.stale_reason = reason
        if source_provider:
            self.source_provider = source_provider
            if (telemetry := current_telemetry()) is not None:
                telemetry.data_provider = source_provider

    def to_meta(self) -> dict[str, Any]:
        as_of = self.data_as_of or datetime.now(UTC)
        meta: dict[str, Any] = {"data_as_of": as_of.astimezone(UTC).isoformat()}
        if self.stale:
            meta["stale"] = True
            meta["stale_reason"] = self.stale_reason
            if self.source_provider:
                meta["source_provider"] = self.source_provider
        return meta


_current: ContextVar[ResponseMeta | None] = ContextVar(
    "mdh_response_meta", default=None
)


def begin(no_cache: bool = False) -> Any:
    """Bind a fresh state to the current context; returns the reset token."""
    return _current.set(ResponseMeta(no_cache=no_cache))


def end(token: Any) -> None:
    _current.reset(token)


def current() -> ResponseMeta:
    """State of the running request; a detached one outside of a request."""
    state = _current.get()
    return state if state is not None else ResponseMeta()


def current_or_none() -> ResponseMeta | None:
    return _current.get()


def envelope(data: Any) -> Any:
    """Response envelope with `meta.data_as_of` (and stale markers) of this request."""
    from app.models.common import EnvelopeMeta, ResponseEnvelope

    return ResponseEnvelope(data=data, meta=EnvelopeMeta(**current().to_meta()))


def csv_headers() -> dict[str, str]:
    return {"X-MDH-Data-As-Of": current().to_meta()["data_as_of"]}
