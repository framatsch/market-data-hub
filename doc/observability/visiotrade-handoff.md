# VisioTrade handoff: MDH request timing and provenance

Market Data Hub 1.7.0 adds optional response headers for VisioTrade's separate `data-load-transparency` change. The MDH version is prepared locally; no deployment is implied. Treat the headers as optional until the VisioTrade environment runs the new version.

- Send the VisioTrade trace ID as `X-Request-ID`. MDH echoes it if it matches `[A-Za-z0-9._:-]{1,128}`; otherwise MDH returns a new ID. Use the returned value to find `request_completed` in MDH logs. Errors also carry the ID.
- On successful market-data responses, including HTTP 304 and CSV, `Server-Timing` reports milliseconds for the layers used (`redis`, `db`, `provider`, `redis-write`) and always includes `total`. Layer intervals can overlap, so don't add the durations to derive a total. Data-route errors carry `total` only.
- `X-Data-Source` distinguishes `redis`, `postgres`, `provider`, and `postgres+provider`. `X-Data-Provider` names the response's provider, which can differ from the requested provider for a stale fallback. Composed calendar earnings can return `a+b`; `/earnings/next` names only the upcoming provider, with optional `last_reported.provider` in the body.
- Keep reading `X-FastAPI-Cache` for the existing `upstreamCache` field. A cache `MISS` is not necessarily a live fetch: the data source may still be PostgreSQL. Keep measuring `mdhMs` in VisioTrade; MDH's `total` measures server wall time until response headers, not the HTTP round trip.

No VisioTrade code changes are part of the MDH change. See the [dashboard specification](grafana-dashboard-spec.md) for the full metric and log reference.
