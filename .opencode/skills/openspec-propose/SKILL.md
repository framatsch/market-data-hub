---
name: openspec-propose
description: Propose a new feature for Market Data Hub. Generates a spec file in specs/ with proposal, design, and task breakdown ready for implementation via plan.agent.md and implement.agent.md.
license: MIT
compatibility: opencode
metadata:
  toolchain: python
---

# Spec Propose

Generate a complete feature spec in `specs/` — proposal, design decisions, and phased task breakdown — ready for `implement.agent.md` to execute.

This replaces the openspec CLI workflow. All state lives in `specs/XX.prompt.md`.

---

## Input

A description of what the user wants to build. A kebab-case name is optional.

If the description is vague, use **AskUserQuestion** to clarify before proceeding.

---

## Steps

### 1. Understand the request

If not provided, ask:
> "What feature do you want to build? Describe the problem it solves and what you expect it to do."

Derive a short kebab-case name (e.g., "add schwab provider" → `add-schwab-provider`).

### 2. Find the next spec number

```bash
ls specs/ | grep -E '^[0-9]+' | sort | tail -1
```

Increment by 1 to get the next number (zero-pad to 2 digits, e.g., `05`).

### 3. Explore the codebase for context

Before writing anything, understand:
- Which existing provider is most similar (for new providers: read `app/providers/ibkr.py` or `app/providers/lseg.py`)
- Which routes/models will be affected (`app/api/`, `app/models/`)
- Which config keys exist in `app/config.py`
- Whether `app/providers/base.py` needs changes

### 4. Check if a new provider agent is needed

If the feature adds a new data provider:
- **The agent file must be created first**, before any spec tasks reference implementation.
- Use `.github/agents/provider.agent.template.md` as the template.
- Add a task in the spec: "Create `.github/agents/<name>.agent.md` from template — commit before any code."

### 5. Write the spec file

Create `specs/NN-<name>.prompt.md` (or `specs/NN.prompt.md` to match existing naming):

```markdown
# Spec: <Human-Readable Feature Name>

## Problem
[What gap or need does this address?]

## Proposed Solution
[High-level description of the approach]

## Design Decisions
[Key architectural or implementation choices, with rationale]

## Scope
**In scope:**
- [item]

**Out of scope:**
- [item]

## Affected Components
- `app/providers/<name>.py` — [what changes]
- `app/api/routes_<name>.py` — [what changes]
- `app/models/<name>.py` — [what changes]
- `app/config.py` — [new env vars, if any]

## Implementation Phases

### Phase 1: [Name]
- [ ] Task 1
- [ ] Task 2

### Phase 2: [Name]
- [ ] Task 3
- [ ] Task 4

## Acceptance Criteria
- [ ] [Verifiable outcome 1]
- [ ] [Verifiable outcome 2]

## Provider Agent (if new provider)
- [ ] Create `.github/agents/<name>.agent.md` from `provider.agent.template.md` **before any implementation tasks**
```

### 6. Show summary

Display:
- Spec file path
- Key design decisions made
- Phase breakdown
- Next step: "Run `implement.agent.md` with this spec, or load `.github/agents/implement.agent.md` to start."

---

## Guardrails

- Never start writing a spec without understanding what the user wants to build
- For new providers: always include the agent-file task as Phase 0 or first task
- Keep tasks atomic — each task should be completable in one focused coding session
- Acceptance criteria must be verifiable (runnable tests or observable behavior)
- Do not implement anything — this skill only produces the spec file
