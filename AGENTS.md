# Market Data Hub — Agent Quick Reference

Single source of truth for all AI agents (OpenCode, GitHub Copilot, Claude). Every line answers: "would an agent miss this without help?"

**Deep technical reference → `.github/copilot-instructions.md`** (error patterns, code templates, technology behaviors — auto-loaded by Copilot/Claude)

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
python -m app.main                                          # HTTP :8000 (MCP disabled by default)
MCP_ENABLED=true python -m app.main                        # HTTP :8000 + MCP at /mcp/sse, /mcp/messages
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload  # HTTP only (dev)
```

- MCP endpoints are on **the same port 8000** (or configured port) under `/mcp/sse` and `/mcp/messages` when `MCP_ENABLED=true`.
- The MCP server is integrated directly into FastAPI (not a separate process).

---

## Environment

- Copy `.env.example` → `.env`. Required: `LSEG_APP_KEY`, `LSEG_USERNAME`, `LSEG_PASSWORD`.
- IBKR: running TWS/Gateway required (Gateway port 4001, TWS paper 7497).
- Settings via `app/config.py` (`SettingsConfigDict(env_file=".env")`). Never commit credentials.
- `MCP_ENABLED=true` enables Model Context Protocol.
- `ENABLED_PROVIDERS=lseg,ibkr` limits loaded providers (default: all).

---

## Architecture

```
HTTP :8000  FastAPI (app/api/routes_*.py)
            → app/services/  → app/providers/registry.py
            → ibkr.py (async ib_async) | lseg.py (sync refinitiv.data) | finnhub.py (async httpx)
            ← app/models/ (Pydantic, all financial values as Decimal)

MCP  :8000  Integrated Router (app/api/mcp.py) — available via SSE
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

## AI Agent Workflows (Unified Config)

All agent configs live in `.github/agents/`. One config consumed by GitHub Copilot (auto-loaded), OpenCode, and Claude.

### Workflow Agents — use for task types

| Agent | When | Time |
|-------|------|------|
| `quickfix.agent.md` | Clear traceback + known error pattern | 2-3 min |
| `debug.agent.md` | Intermittent, multi-component, unclear root cause | 20-30 min |
| `plan.agent.md` | New feature → generates `specs/XX.prompt.md` + agent file for new providers | 15-30 min |
| `implement.agent.md` | Spec ready in `specs/` → phase-by-phase impl; loads domain agent as harness | 1-3 hr |

### Domain Expert Agents — use for component work

| Agent file | Owns | Trigger when working on… |
|------------|------|--------------------------|
| `architect.agent.md` | System design, cross-component interfaces, delegation | Feature spanning 2+ components |
| `ibkr.agent.md` | `app/providers/ibkr.py`, IBKR config keys | IBKR connection, options, NaN, subscription errors |
| `lseg.agent.md` | `app/providers/lseg.py`, LSEG config keys | RIC lookup, session, caching, rate limiting |
| `finnhub.agent.md` | `app/providers/finnhub.py`, `mock_news.py` | News, sentiment, Finnhub |
| `fastapi.agent.md` | `app/api/`, `app/models/`, `app/dependencies.py` | Routes, Pydantic models, DI, CSV export |
| `mcp.agent.md` | MCP tools in `app/api/mcp.py`, SSE on app port | Exposing data to LLM clients via MCP |
| `infra.agent.md` | `Dockerfile`, `k8s/`, `ci.yml`, `app/config.py` | Docker, K8s, CI, env vars |
| `provider.agent.template.md` | Template for new providers | Adding any new data provider |

**Architect-first rule:** Any change touching 2+ domain agents → start with `architect.agent.md`.

**New provider rule:** Agent file must be committed **before any code**. `plan.agent.md` generates it automatically. Manual: copy `provider.agent.template.md`, fill placeholders, commit.

### Copilot chat shorthand

```
@workspace Quick Fix Mode    ❌ [traceback]
@workspace Debug Mode        Problem: … / When: always|intermittent|after change
@workspace Plan Feature Mode Feature: …
@workspace Implement Feature Mode  Spec: specs/XX.prompt.md
```

### OpenCode / Claude skills (gstack)

- `investigate` — systematic root-cause debugging (4-phase: investigate → analyze → hypothesize → implement)
- `ship` — runs tests, bumps VERSION, creates PR

---

## Docker / CI

```bash
docker build -t market-data-hub:latest .
docker run --env-file .env -p 8000:8000 -p 8001:8001 market-data-hub:latest
curl http://localhost:8000/health
```

CI (`.github/workflows/ci.yml`): `libopenblas-dev` → `uv sync` → `ruff check app/` → `pytest` → Docker build+push to GHCR on `main`, `develop`, `v*` tags.

---

## High-Value Files

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI + FastMCP init, exception handlers, both-server startup |
| `app/config.py` | All settings and env var names |
| `app/providers/base.py` | Abstract interfaces every provider must implement |
| `app/providers/ibkr.py` | IBKR async provider (`_is_valid`, `_to_decimal`, `_ensure_connection`) |
| `app/providers/lseg.py` | LSEG sync provider (`_ticker_to_ric`, session, cache) |
| `app/utils/errors.py` | `AppError` hierarchy and HTTP status mapping |
| `.github/copilot-instructions.md` | Error patterns, code templates, technology behaviors |
| `.github/agents/` | All workflow and domain agent definitions |
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
