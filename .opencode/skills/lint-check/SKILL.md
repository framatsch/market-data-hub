---
name: lint-check
description: Run ruff on app/ to catch style and import errors before committing. Use before every commit that touches Python files.
license: MIT
compatibility: opencode
metadata:
  toolchain: uv, ruff
  runner: python skills/lint_check.py
---

## What I do

Run the linting pipeline on `app/` (CI scope) and optionally `tests/` and `scripts/`, reporting all issues with file paths and line numbers.

## Tools used

| Tool | What it checks |
|------|----------------|
| `ruff check` | Style, imports, common bugs (E, F, I, UP, B, SIM rules) |

No mypy in this project — type safety is enforced via Pydantic models at runtime.

## When to use me

- Before every commit that touches Python files in `app/`
- When CI reports a lint failure and you need to reproduce locally
- After adding a new module (check imports are clean)

## How to run

```bash
# CI scope only (app/) — matches what CI runs
uv run ruff check app/

# Full scope including tests/ and scripts/
python skills/lint_check.py --all

# App only
python skills/lint_check.py --app

# Tests only
python skills/lint_check.py --tests

# Auto-fix safe issues
python skills/lint_check.py --all --fix

# CI mode (exits 1 on any failure)
python skills/lint_check.py --all --ci
```

## Scope boundaries

| Scope | Linted by CI? | Notes |
|-------|--------------|-------|
| `app/` | Yes | Always lint before committing |
| `tests/` | No | Use `--all` or `--tests` locally |
| `scripts/diagnostics/` | No | Dev-only scripts, excluded from CI |

## Common ruff rules in this project

- `I` — import ordering (fix first, always)
- `F401` — unused imports (remove imports YOUR changes made unused; leave pre-existing ones alone)
- `E501` — line length (max 88 chars)
- `UP` — pyupgrade suggestions

## Fixing errors

- Run `python skills/lint_check.py --all --fix` for auto-fixable issues.
- Manual fixes needed for: unused variables, logic issues, complex refactors.
- After fixing, re-run to confirm clean output before committing.
