---
name: unit-test
description: Run the pytest test suite with coverage reporting. Use after implementing a feature, when debugging a failing test, or before opening a PR.
license: MIT
compatibility: opencode
metadata:
  toolchain: uv, pytest
---

## What I do

Run the Market Data Hub test suite and report coverage. Help interpret failures by understanding which provider or layer the test exercises.

## Test architecture

| Layer | Location | Requires live services? | What it tests |
|-------|----------|------------------------|---------------|
| Unit | `tests/` (non-integration) | No | Provider logic, model validation, CSV export, service routing |
| Integration | `tests/integration/` | Yes — IBKR Gateway or LSEG | Full round-trip through real external APIs |

## When to use me

- After implementing a new feature to verify no regressions
- When debugging a failing test
- Before opening a PR (reproduces the `test` CI job)
- After changing a provider's error handling or data conversion logic

## How to run

```bash
# All unit tests (no live services needed) — matches CI
uv run pytest --maxfail=1 --disable-warnings

# Single test file
uv run pytest tests/test_ibkr.py --disable-warnings

# Single test by name
uv run pytest -k "test_get_last_price" --disable-warnings

# With coverage report
uv run pytest --cov=app --cov-report=term-missing --disable-warnings

# Integration tests (requires IBKR Gateway or valid LSEG credentials)
uv run pytest tests/integration/ --disable-warnings
```

## Prerequisites for integration tests

- **IBKR:** TWS or Gateway must be running. Set in `.env`:
  ```
  IBKR_HOST=127.0.0.1
  IBKR_PORT=4001   # Gateway; 7497 for TWS paper
  ```
- **LSEG:** Valid credentials in `.env`:
  ```
  LSEG_APP_KEY=...
  LSEG_USERNAME=...
  LSEG_PASSWORD=...
  ```

Never run integration tests in CI — they are excluded from `.github/workflows/ci.yml`.

## Interpreting failures

| Error pattern | Likely cause |
|--------------|-------------|
| `ProviderConnectionError` in unit test | Test is hitting a real provider — should be mocked |
| `ValidationError` | Pydantic model field type mismatch; check `Decimal` vs `float` |
| `math.isnan` or NaN-related | IBKR NaN not guarded — use `_is_valid()` helper |
| `RDError` | LSEG session not initialized — check `_get_session()` mock |
| Import error | Run `uv sync --frozen --all-extras` to refresh deps |

## Pytest config

All options (addopts, test discovery paths, coverage settings) are in `pyproject.toml`. Running `pytest` without flags picks them up automatically.
