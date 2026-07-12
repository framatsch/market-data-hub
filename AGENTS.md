# Market Data Hub — Agent Quick Reference

Single source of truth for all AI agents (OpenCode, GitHub Copilot, Claude). Every line answers: "would an agent miss this without help?"

**Deep technical reference → `.github/copilot-instructions.md`** (error patterns, code templates, technology behaviors — auto-loaded by Copilot/Claude)

---

## Memory

- Engram MCP memory is available (`mem_save`, `mem_search`, `mem_context`, `mem_session_summary`).
- Save proactively with `mem_save` after significant work: bug fixes, decisions, discoveries, config changes, conventions.
- After any compaction or context reset, call `mem_context` before continuing.

---

## Setup & Commands

```bash
# Dev setup (match CI exactly)
sudo apt-get install -y libopenblas-dev   # Linux only, required before uv sync
uv sync --frozen --all-extras
uv pip install ruff                        # not in pyproject extras

# Lint → Test (always in this order)
uv run ruff check app/                    # CI lint gate (app/ only)
python skills/lint_check.py --all         # also covers tests/
uv run pytest --maxfail=1 --disable-warnings

# Production / Dockerfile
uv sync --frozen --no-dev
```

- `pyproject.toml` + `uv.lock` are the dependency source of truth. Ignore any `requirements.txt`.
- `httpx==0.26.0` is pinned via `[tool.uv]` — resolves conflict between `refinitiv-data` and `fastmcp`. Do not change.
- Pytest config (addopts, discovery, coverage) lives in `pyproject.toml`.

---

## Running the Service

```bash
python -m app.main                                          # HTTP on APP_PORT (default 8000, MCP disabled by default)
MCP_ENABLED=true python -m app.main                        # + MCP at /mcp, /mcp/sse, /mcp/messages
APP_ENV=dev RELOAD=true python -m app.main                 # local dev with auto-reload (WatchFiles)
```

- MCP endpoints are on **the same port** (`APP_PORT`, default 8000): Claude remote MCP uses `/mcp`; legacy SSE uses `/mcp/sse` + `/mcp/messages`.
- The MCP server is integrated directly into FastAPI (not a separate process).
- **Host/port** come from `APP_HOST` / `APP_PORT` — `python -m app.main` reads them; don't pass `--host`/`--port`.
- **Auto-reload is OFF by default.** It only fires when **both** `APP_ENV=dev` **and** `RELOAD=true`. Never enable reload in production — WatchFiles rebuilds/re-watches the source tree on every change and is not built for stability. A prod container logging `reload` / `WatchFiles` / "Will watch for changes" is misconfigured (the old `/.dockerenv` heuristic was removed; `APP_ENV=dev` alone no longer triggers reload).
- **Do NOT start prod with `uvicorn ... --reload`.** Production runs via the image default `python -m app.main` (Dockerfile `CMD`).

---

## Environment

- Copy `.env.example` → `.env`. Provider credentials are managed in encrypted `keys.db` via Admin UI/API, not provider-specific env vars.
- IBKR: running TWS/Gateway required (Gateway port 4001, TWS paper 7497).
- Settings via `app/config.py` (`SettingsConfigDict(env_file=".env")`). Never commit credentials.
- `MCP_ENABLED=true` enables Model Context Protocol.
- `ENABLED_PROVIDERS=lseg,ibkr` limits loaded providers (default: all).
- **`APP_ENV`** = `dev` | `test` | `prod`. Only `dev` allows auto-reload (with `RELOAD=true`). `prod` forces admin auth on. `RELOAD` (default `false`) gates WatchFiles.
- **Admin login** (`/admin/` UI, OpenID): controlled by `ADMIN_AUTH_ENABLED` (default `true`). To disable login in a non-prod deployment, set `APP_ENV=test` + `ADMIN_AUTH_ENABLED=false` — use `test`, **not** `dev`, so you don't accidentally enable dev-only behavior. `APP_ENV=prod` rejects `ADMIN_AUTH_ENABLED=false` and requires `ADMIN_OIDC_ISSUER` + `ADMIN_OIDC_CLIENT_ID` (see `_validate_production_admin_auth` in `app/config.py`).

---

## Architecture

```
HTTP :8000  FastAPI (app/api/routes_*.py)
            → app/services/  → app/providers/registry.py
            → ibkr.py (async ib_async) | lseg.py (sync refinitiv.data) | finnhub.py (async httpx)
            ← app/models/ (Pydantic, all financial values as Decimal)

MCP  :8000  Integrated Router (app/api/mcp.py) — `/mcp` Streamable HTTP + legacy SSE
```

Provider details, error patterns, and code templates → `.github/copilot-instructions.md`

---

## Commit Convention

`python skills/commit_helper.py` — never commit without explicit user approval.

| Emoji | Category | When |
|-------|----------|------|
| 🔧 | Fix | Bug fixes |
| ✨ | Add | New features |
| 🔄 | Refactor | Reorganization |
| 🔌 | Provider | IBKR/LSEG/provider changes |
| 🌐 | API | Endpoint changes |
| 📚 | Docs | Documentation |
| ⚡ | Perf | Performance |

---

## Agent Guidance

- Use this file for high-signal project facts only; move long workflows into `.opencode/skills/*/SKILL.md` or `.github/copilot-instructions.md`.
- For deep provider/API behavior and error patterns, read `.github/copilot-instructions.md` only when relevant.
- For OpenSpec changes, use the matching `.opencode/skills/openspec-*` skill.
- For code review requests, follow the managed OCR block below.

### Copilot Chat Shorthand

```
@workspace Quick Fix Mode    ❌ [traceback]
@workspace Debug Mode        Problem: … / When: always|intermittent|after change
@workspace Plan Feature Mode Feature: …
@workspace Implement Feature Mode  Spec: specs/XX.prompt.md
```

### OpenCode / Claude Skills

- `investigate` — systematic root-cause debugging (4-phase: investigate → analyze → hypothesize → implement)
- `ship` — runs tests, bumps VERSION, creates PR

---

## Docker / CI

```bash
docker build -t market-data-hub:latest .
docker run --env-file .env -p 8000:8000 market-data-hub:latest
curl http://localhost:8000/health
```

CI (`.github/workflows/ci.yml`): `libopenblas-dev` → `uv sync` → `ruff check app/` → `pytest` → Docker build+push to GHCR on `main`, `develop`, `v*` tags.

---

## High-Value Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app setup, exception handlers, startup/shutdown |
| `app/config.py` | All settings and env var names |
| `app/providers/base.py` | Abstract interfaces every provider must implement |
| `app/providers/ibkr.py` | IBKR async provider (`_is_valid`, `_to_decimal`, `_ensure_connection`) |
| `app/providers/lseg.py` | LSEG sync provider (`_ticker_to_ric`, session, cache) |
| `app/utils/errors.py` | `AppError` hierarchy and HTTP status mapping |
| `.github/copilot-instructions.md` | Error patterns, code templates, technology behaviors |
| `skills/lint_check.py` | Pre-commit lint helper |
| `skills/commit_helper.py` | Commit message generator |
| `specs/` | Feature specs generated by `plan.agent.md` |
| `pyproject.toml` | Dependency truth, pytest config, uv pin overrides |

<!-- OCR:START -->
## Open Code Review Instructions

These instructions are for AI assistants handling code review in this project.

Always open `.ocr/skills/SKILL.md` when the request:
- Asks for code review, PR review, or feedback on changes
- Mentions "review my code" or similar phrases
- Wants multi-perspective analysis of code quality
- Asks to map, organize, or navigate a large changeset

Use `.ocr/skills/SKILL.md` to learn:
- How to run the 8-phase review workflow
- How to generate a Code Review Map for large changesets
- Available reviewer personas and their focus areas
- Session management and output format

Keep this managed block so `ocr init` can refresh the instructions.

<!-- OCR:END -->
