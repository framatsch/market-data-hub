# Market Data Hub — Gemini Agent Notes

Use `AGENTS.md` as the project quick reference. Keep this file short so Gemini and Antigravity sessions load only the essentials.

## Memory

You have access to Engram persistent memory via MCP tools (`mem_save`, `mem_search`, `mem_context`, `mem_session_summary`, etc.).

- Save proactively after significant work; do not wait to be asked.
- After any compaction or context reset, call `mem_context` to recover session state before continuing.

## Project Basics

- Dependency source of truth: `pyproject.toml` + `uv.lock`; ignore `requirements.txt`.
- Run checks in this order before committing Python changes: `uv run ruff check app/`, `python skills/lint_check.py --all`, then `uv run pytest --maxfail=1 --disable-warnings`.
- Provider credentials belong in encrypted `keys.db` via Admin UI/API, not provider-specific environment variables.
- MCP runs inside FastAPI on the same HTTP port; Claude remote MCP uses `/mcp`, legacy SSE uses `/mcp/sse` + `/mcp/messages`.
