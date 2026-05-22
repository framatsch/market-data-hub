## Context

Market Data Hub exposes a unified `GET /prices/history/{symbol}` endpoint backed by swappable provider implementations. IBKR and LSEG already implement `BasePriceProvider`. Schwab is being added as a third price provider using the `schwab-py` open-source wrapper around the Schwab Individual Trader API.

The `schwab-py` library handles OAuth2 token management, HTTP via `httpx`, and provides typed enum constants for all API parameters. It supports both sync and async modes; the project standard is async-first so the client is always created with `asyncio=True`.

Current state: `app/providers/schwab.py` does not exist. The Schwab agent file (`.github/agents/schwab.agent.md`) was created in a prior session and documents the integration contract.

---

## Goals / Non-Goals

**Goals:**
- Implement `BasePriceProvider.get_last_price` using `client.get_quote()`.
- Implement `BasePriceProvider.get_historical_prices` using the appropriate `schwab-py` convenience method (`get_price_history_every_day`, `get_price_history_every_minute`, etc.) selected by interval string.
- Register `SchwabProvider` in `app/providers/registry.py` under key `"schwab"`.
- Add `SCHWAB_*` config keys; provider is disabled (no-op) when `SCHWAB_API_KEY` is empty.
- Cover the implementation with unit tests using mocked HTTP responses.

**Non-Goals:**
- Options chain retrieval (`BaseOptionsProvider`) — deferred to a future change.
- Company fundamentals / search (`BaseCompanyProvider`) — deferred.
- Order placement — out of scope for a data-hub service.
- WebSocket / streaming — Schwab API has no streaming endpoint; use IBKR for live data.
- Multi-account selection — always use the first linked account hash.

---

## Decisions

### Decision 1: Use `schwab-py` convenience methods, not the raw `get_price_history` endpoint

**Chosen:** Map the `interval` parameter to one of `get_price_history_every_minute`, `get_price_history_every_five_minutes`, … `get_price_history_every_week`.

**Alternative considered:** Call the raw `get_price_history()` directly with `PeriodType`, `FrequencyType`, and `Frequency` enums.

**Rationale:** The convenience methods encapsulate the non-obvious enum combinations and are documented clearly. The raw endpoint's period/frequency interaction is undocumented and fragile. Using convenience methods reduces maintenance burden and aligns with `schwab-py`'s own recommendation.

---

### Decision 2: Token stored on disk; pre-creation required for server deployments

**Chosen:** Use `easy_client()` which loads a token from `SCHWAB_TOKEN_PATH` if it exists, or opens a browser login flow if it doesn't. In production/headless environments, the token must be pre-created via `schwab-generate-token.py` and copied to the container.

**Alternative considered:** Use `client_from_access_functions()` with a custom read/write backend (e.g., environment variable or secrets manager).

**Rationale:** The access-functions approach adds significant complexity for a feature used by a single Schwab account. File-based storage is sufficient for the current use case. The 7-day token expiry requires manual intervention regardless of storage strategy; adding complexity does not eliminate that operational burden.

---

### Decision 3: `SchwabProvider` is async-native with `asyncio.to_thread` for blocking init

**Chosen:** The `schwab-py` client is created with `asyncio=True` so all API calls are coroutines. The one-time `easy_client()` call (which may perform disk I/O) is wrapped in `asyncio.to_thread` to avoid blocking the event loop.

**Alternative considered:** Create the client synchronously in `__init__`.

**Rationale:** Synchronous initialization in an async FastAPI startup hook would block the event loop during token file parsing. Wrapping in `asyncio.to_thread` keeps the pattern consistent with the LSEG provider.

---

### Decision 4: Interval → method mapping via a dispatch dict

**Chosen:**
```python
_INTERVAL_METHODS = {
    "1m":  "get_price_history_every_minute",
    "5m":  "get_price_history_every_five_minutes",
    "10m": "get_price_history_every_ten_minutes",
    "15m": "get_price_history_every_fifteen_minutes",
    "30m": "get_price_history_every_thirty_minutes",
    "1d":  "get_price_history_every_day",
    "1w":  "get_price_history_every_week",
}
```
Unsupported intervals raise `DataValidationError`.

**Rationale:** A dict is more readable and testable than a chain of `if/elif`. Adding new intervals is a one-line change.

---

### Decision 5: OHLCV bar parsing — defensive field access

Schwab returns candles as:
```json
{ "candles": [ { "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1000, "datetime": 1234567890000 } ] }
```
`datetime` is milliseconds since epoch (integer). Convert to UTC `datetime` via `datetime.utcfromtimestamp(ms / 1000)`. All price fields converted to `Decimal(str(...))`.

---

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| Token expires every 7 days — provider silently fails | `ProviderConnectionError` raised with hint message; document in ops runbook |
| App stays in `Approved - Pending` after Schwab portal changes | Catch `401` / `OAuthError` and surface actionable error message |
| `easy_client()` opens browser in server environment | Document: pre-create token with `schwab-generate-token.py` before deploying |
| Rate limits undocumented by Schwab | Conservative default `SCHWAB_RATE_LIMIT_PER_SEC=5`; raise `ProviderTimeoutError` on 429 |
| Historical data limited to equities/ETFs | Document clearly; futures symbols return `DataNotFoundError` |
| Single token file — concurrent access corrupts token | Single `SchwabProvider` singleton in registry; never create multiple instances |

---

## Migration Plan

1. Add `schwab-py` to `pyproject.toml` dependencies.
2. Add `SCHWAB_*` keys to `app/config.py` (all default to empty/zero — no breakage).
3. Add keys to `.env.example` with explanatory comments.
4. Create `app/providers/schwab.py`.
5. Register in `app/providers/registry.py`.
6. Add unit tests.
7. Verify with `uv run ruff check app/` and `uv run pytest tests/ -k schwab`.

**Rollback:** Remove `SCHWAB_API_KEY` from `.env` — provider is effectively disabled. No database migrations, no schema changes.

---

## Open Questions

- Should `get_last_price` use `get_quotes()` (supports `/ES` futures syntax) or `get_quote()` (cleaner for equities)? → Propose `get_quotes([symbol])` with normalization; handles both without branching.
- Do we need a `SCHWAB_DEFAULT_ACCOUNT_INDEX` config to support users with multiple linked accounts? → Deferred; single-account assumption is fine for now.
