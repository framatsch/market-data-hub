---
name: safe-commit
description: Run the full pre-commit gate (lint → test) and commit only when clean. Use before every commit to ensure CI will pass.
license: MIT
compatibility: opencode
metadata:
  toolchain: python, uv
---

# Safe Commit Skill

Orchestrates the pre-commit checks for Market Data Hub to ensure the CI build passes before committing. Runs lint and tests, fixes issues where possible, then commits using the project commit convention.

## Workflow

Follow these steps sequentially — do not skip ahead:

### 1. Lint

Load and follow the `lint-check` skill, or run directly:

```bash
uv run ruff check app/
python skills/lint_check.py --all
```

Fix any issues. Re-run until clean.

### 2. Tests

```bash
uv run pytest --maxfail=1 --disable-warnings
```

If tests fail, fix the implementation and re-run. Do not proceed to commit with failing tests.

**Note:** Tests that require live IBKR/LSEG services (`tests/integration/`) are excluded from this gate — run them separately only when services are available.

### 3. Commit

Once lint and tests both pass:

```bash
python skills/commit_helper.py
```

This generates a commit message following the project convention (`[emoji] [Category]: [description]`). Review the proposed message, confirm with user, then commit.

**Never commit without explicit user approval.**

## Commit convention quick reference

| Emoji | Category | When |
|-------|----------|------|
| 🔧 | Fix | Bug fixes |
| ✨ | Add | New features |
| 🔄 | Refactor | Reorganization |
| 🔌 | Provider | IBKR/LSEG/provider changes |
| 🌐 | API | Endpoint changes |
| 📚 | Docs | Documentation |
| ⚡ | Perf | Performance |
| ⚙️ | Config | Config/version changes |

## What this skill does NOT do

- Push to remote (use the `ship` gstack skill for that)
- Run integration tests against live services
- Bump version (use the `bump-version` skill for that)
