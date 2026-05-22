---
name: refactor-pro
description: Identify and eliminate technical debt, dead code, and bloat in app/. Use when the codebase feels cluttered, a file has grown too large, or patterns have drifted between providers.
license: MIT
compatibility: opencode
metadata:
  toolchain: python, uv, ruff
---

# Skill: Technical Debt & Code Bloat Elimination

Specialized for identifying and removing redundant code, dead logic, and inconsistent patterns in the Market Data Hub Python backend (`app/`).

## Operational Procedures

### 1. DRY Audit (Don't Repeat Yourself)

- Scan provider files (`ibkr.py`, `lseg.py`, `finnhub.py`) for near-identical logic blocks.
- Common duplication targets:
  - Rate limiting implementations (each provider has its own — candidate for `app/utils/`)
  - Response validation / defensive DataFrame/dict parsing
  - Symbol normalization / conversion logic
  - Error wrapping patterns around third-party SDK exceptions
- Propose centralized utility functions in `app/utils/` or `app/providers/base.py`.

### 2. Dead Code & Unused Assets

- Functions defined but never called (check with `ruff check --select F401,F811`)
- Unused imports in every `app/` file
- Config keys in `app/config.py` not referenced anywhere in `app/`
- Stubs in providers marked `TODO` for longer than one release

### 3. Complexity Review

- Provider methods longer than ~60 lines — candidates for helper extraction
- Nested `try/except` blocks deeper than 2 levels
- Flag files exceeding 500 lines for modularization review
- `app/providers/ibkr.py` is the highest-risk file for complexity creep

### 4. Pattern Drift Between Providers

Each provider must follow the same universal rules (from `provider.agent.template.md`):
- `Decimal` (not `float`) for all financial values
- `AppError` subclasses only — no raw `Exception`
- Rate limiting hook before every external call
- Symbol normalization in a single `_normalize_symbol` method
- Defensive response validation

Check that `ibkr.py`, `lseg.py`, and `finnhub.py` all conform. Flag any provider that has drifted.

## Output Requirements

Generate a "Refactoring Candidates" report:

```
## Refactoring Candidates

### [File path] — [Category]
- Lines: X–Y
- Issue: [description]
- LOC reduction estimate: ~N lines
- Classification: Safe to Delete | Requires Review
```

## Git Workflow

1. Create a branch: `refactor/[description]-[YYYY-MM-DD]`
2. Apply one logical change per commit: `🔄 Refactor: [what changed]`
3. After each commit: `uv run ruff check app/ && uv run pytest --maxfail=1 --disable-warnings`
4. Never commit with failing tests or lint errors
5. Never commit without explicit user approval

## Guardrails

- Apply Karpathy's Surgical Changes rule: touch only what you must
- Don't "improve" adjacent code that isn't broken
- Don't remove pre-existing dead code unless explicitly asked — mention it instead
- Every changed line must trace directly to the refactoring goal
- Integration tests in `tests/integration/` require live services — skip them in the validation step
