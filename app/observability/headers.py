"""OpenAPI descriptions of the common market-data response headers."""

from typing import Any

EXPOSED_HEADERS = [
    "Server-Timing",
    "X-FastAPI-Cache",
    "X-Data-Source",
    "X-Data-Provider",
    "X-Request-ID",
    "X-MDH-Data-As-Of",
]

DATA_RESPONSE_HEADERS: dict[str, Any] = {
    "Server-Timing": {
        "description": "Wall-clock layer and total durations in milliseconds.",
        "schema": {"type": "string"},
    },
    "X-Data-Source": {
        "description": "Layer or layers that supplied the response data.",
        "schema": {
            "type": "string",
            "enum": ["redis", "postgres", "provider", "postgres+provider"],
        },
    },
    "X-Data-Provider": {
        "description": "Data provider, or upcoming+history for composed earnings.",
        "schema": {"type": "string"},
    },
    "X-FastAPI-Cache": {
        "description": (
            "Response-cache result; absent when the cache decorator is not used, "
            "caching is disabled or no-store is requested. MISS can also mean a "
            "no-cache refresh, a fresh response with TTL 0, or Redis cooldown."
        ),
        "schema": {"type": "string", "enum": ["HIT", "MISS"]},
    },
    "X-Request-ID": {
        "description": "The validated client request ID or a generated UUID4 hex ID.",
        "schema": {"type": "string", "pattern": "^[A-Za-z0-9._:-]{1,128}$"},
    },
    "Cache-Control": {
        "description": "Response cache lifetime or no-store when caching is not permitted.",
        "schema": {"type": "string"},
    },
}

CSV_RESPONSE_HEADERS = {
    **DATA_RESPONSE_HEADERS,
    "X-MDH-Data-As-Of": {
        "description": "UTC timestamp of the underlying data, when supplied with CSV output.",
        "schema": {"type": "string", "format": "date-time"},
    },
}
