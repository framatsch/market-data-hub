# 🛠️ Market Data Hub Skills

Reusable automation scripts for development workflows. These skills can be invoked by developers, CI/CD pipelines, or GitHub Copilot.

## 📋 Available Skills

### 1. **lint_check.py** - Code Linting
Runs `ruff check` on app/, tests/, and optionally scripts/.

**Usage:**
```bash
# Check everything (app + tests)
python skills/lint_check.py --all

# Check specific components
python skills/lint_check.py --app
python skills/lint_check.py --tests
python skills/lint_check.py --scripts  # Optional (development scripts)

# Auto-fix issues
python skills/lint_check.py --all --fix

# CI mode (exit 1 on errors)
python skills/lint_check.py --all --ci
```

**Copilot Integration:**
```
User: "Check code quality before commit"
Copilot: [runs lint_check.py --all]
         [shows results]

User: "Fix linting errors"
Copilot: [runs lint_check.py --all --fix]
```

---

### 2. **commit_helper.py** - Commit Message Generator
Generate and validate commits according to Market Data Hub standards.

**Usage:**
```bash
# Interactive guided mode
python skills/commit_helper.py

# Auto-generate from git diff
python skills/commit_helper.py --auto

# Validate last commit
python skills/commit_helper.py --validate

# Preview without committing
python skills/commit_helper.py --preview

# Add all files before commit
python skills/commit_helper.py --add-all
```

**Supported Categories:**
- 🔧 Fix: Bug fixes
- ✨ Add: New features
- 📚 Docs: Documentation
- 🔄 Refactor: Code reorganization
- ⚡ Perf: Performance improvements
- 🐛 Debug: Debugging changes
- 🔌 Provider: Provider-specific changes (IBKR/LSEG)
- 🌐 API: API endpoint changes

**Copilot Integration:**
```
User: "Create commit for these changes"
Copilot: [runs commit_helper.py --auto]
         [shows suggested category and message]
         [asks for approval]
```

---

## 🎯 Project-Specific Notes

**Market Data Hub Structure:**
- `app/` - Main application code (providers, API routes, models)
- `tests/` - Integration and unit tests
- `scripts/diagnostics/` - Development/debugging scripts (excluded from CI)
- `k8s/` - Kubernetes deployment manifests
- `doc/` - Documentation and architecture guides

**Provider Patterns:**
- IBKR: Async with `ib_async` library
- LSEG: Synchronous with `refinitiv.data` SDK
- Follow patterns in `.github/copilot-instructions.md`
- Deploy strategies
- Get job status
- Stream logs
- Rollback deployments

---

## 🔧 Setup

**Dependencies:**
```bash
pip install click rich ruff
```

**Make scripts executable:**
```bash
chmod +x skills/*.py
```

---

## 🤖 Copilot Integration

These skills are designed to be called by GitHub Copilot via `run_in_terminal` tool.

**Example workflow:**
```python
# Copilot recognizes intent
User: "Check if my code will pass CI"

# Copilot runs skill
run_in_terminal("python skills/lint_check.py --all --ci")

# Copilot parses output and reports
"✅ All checks passed! CI builds should succeed."
```

**Context loading:**
Skills are referenced in `.github/copilot-instructions.md` for automatic discovery.

---

## 📦 Directory Structure

```
skills/
├── __init__.py           # Package initialization
├── README.md             # This file
├── lint_check.py         # Linting skill ✅
├── strategy_test.py      # Strategy testing (planned)
├── order_validator.py    # Order validation (planned)
├── dashboard_query.py    # Dashboard queries (planned)
└── k8s_deploy.py         # K8s deployment (planned)
```

---

## 🧪 Testing Skills

**Test linting skill:**
```bash
# Should show current state
python skills/lint_check.py --all

# Fix and verify
python skills/lint_check.py --all --fix
python skills/lint_check.py --all --ci
```

---

## 🔐 CI/CD Integration

**GitHub Actions example:**
```yaml
- name: Run linting checks
  run: |
    pip install click rich ruff
    python skills/lint_check.py --all --ci
```

**Pre-commit hook:**
```bash
#!/bin/bash
# .git/hooks/pre-commit
python skills/lint_check.py --all --ci || exit 1
```

---

## 📝 Skill Development Guidelines

When creating new skills:

1. **Click CLI interface** - Use `@click.command()` for consistency
2. **Rich output** - Use `rich.console` for formatted output
3. **Structured results** - Return parseable data (JSON/table)
4. **Exit codes** - 0=success, 1=failure (for CI)
5. **Documentation** - Add usage examples in docstring
6. **Copilot-friendly** - Clear output that Copilot can parse

**Template:**
```python
#!/usr/bin/env python3
"""Skill description."""

import click
from rich.console import Console

console = Console()

@click.command()
@click.option('--flag', is_flag=True, help='Description')
def main(flag: bool):
    """Skill main function."""
    console.print("[green]Success[/green]")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

---

## 🎯 Next Steps

1. ✅ Linting skill implemented
2. 🔜 Test skill for strategies
3. 🔜 Order validation skill
4. 🔜 Dashboard query skill
5. 🔜 K8s deployment skill

---

**Questions?** See [.github/copilot-instructions.md](.github/copilot-instructions.md) for integration details.
