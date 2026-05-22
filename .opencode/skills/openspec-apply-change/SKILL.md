---
name: openspec-apply-change
description: Implement a feature spec from specs/ phase by phase. Loads the relevant domain agent as a harness before coding. Use when a spec exists and the user wants to start or continue implementation.
license: MIT
compatibility: opencode
metadata:
  toolchain: python, uv
---

# Spec Implement

Execute a feature spec from `specs/` using the domain agent workflow defined in `.github/agents/implement.agent.md`.

---

## Input

Optionally specify a spec file (e.g., `specs/05-add-schwab-provider.prompt.md`). If omitted, list available specs and ask.

---

## Steps

### 1. Select the spec

If not specified:
```bash
ls specs/
```
Show available specs. Use **AskUserQuestion** to let the user select if more than one exists.

### 2. Read the spec

Read the full spec file. Identify:
- Phases and tasks
- Affected components
- Whether a new provider agent is required

### 3. Load the domain agent harness

Before writing any code, identify which domain agent owns the primary component:

| Component | Agent |
|-----------|-------|
| `app/providers/ibkr.py` | `.github/agents/ibkr.agent.md` |
| `app/providers/lseg.py` | `.github/agents/lseg.agent.md` |
| `app/providers/finnhub.py` | `.github/agents/finnhub.agent.md` |
| New provider | `.github/agents/<name>.agent.md` — **must exist before proceeding** |
| `app/api/` | `.github/agents/fastapi.agent.md` |
| `app/main.py` MCP tools | `.github/agents/mcp.agent.md` |
| `Dockerfile`, `k8s/`, CI | `.github/agents/infra.agent.md` |
| 2+ components | `.github/agents/architect.agent.md` |

Read the agent file and apply its rules throughout implementation.

**Hard stop:** If the spec requires a new provider and `.github/agents/<name>.agent.md` does not exist, stop and create it from `.github/agents/provider.agent.template.md` before proceeding.

### 4. Show current progress

Display:
- Spec name
- Total tasks / completed / remaining
- Current phase

### 5. Implement tasks

For each pending task, in order:

1. Make the minimal code change required
2. Follow all rules from the loaded domain agent (Decimal, AppError, rate limiting, etc.)
3. After each task: run lint + tests
   ```bash
   uv run ruff check app/
   uv run pytest --maxfail=1 --disable-warnings
   ```
4. Mark the task complete in the spec file: `- [ ]` → `- [x]`
5. Continue to the next task

**Pause if:**
- A task is ambiguous — ask before implementing
- Lint or tests fail — fix before marking complete
- Implementation reveals a design issue — surface it, update the spec if needed
- User interrupts

### 6. On completion or pause

Show:
- Tasks completed this session
- Overall progress (N/M complete)
- If all done: suggest running `safe-commit` skill then `ship` skill
- If paused: explain why and wait

---

## Output format

```
## Implementing: <spec-name>
## Domain agent: <agent-file>

Working on: Phase 1, Task 2 — <task description>
[implementation...]
✓ Done. Lint clean. Tests pass.

Working on: Phase 1, Task 3 — <task description>
...
```

---

## Guardrails

- Always read the full spec before starting
- Always load the domain agent before writing code
- Never mark a task complete if lint or tests fail
- Never commit — use `safe-commit` skill after implementation is done
- Never implement without a spec — use `openspec-propose` to create one first
- Keep changes minimal and scoped to each task
