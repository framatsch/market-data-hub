---
name: openspec-archive-change
description: Mark a completed spec as done by moving it to specs/archive/. Use after all tasks in a spec are complete and the feature is committed.
license: MIT
compatibility: opencode
metadata:
  toolchain: python
---

# Spec Archive

Move a completed spec from `specs/` to `specs/archive/` after all tasks are done and the feature is committed.

---

## Input

Optionally specify the spec file. If omitted, list available specs and ask.

---

## Steps

### 1. Select the spec

If not specified:
```bash
ls specs/
```
Use **AskUserQuestion** to let the user select. Only show non-archived specs.

### 2. Check task completion

Read the spec file and count:
- `- [ ]` → incomplete tasks
- `- [x]` → complete tasks

If incomplete tasks exist, warn the user and confirm before proceeding.

### 3. Check the work is committed

```bash
git status
git log --oneline -5
```

If there are uncommitted changes, warn the user. Suggest running the `safe-commit` skill first.

### 4. Archive the file

```bash
mkdir -p specs/archive
mv specs/<filename> specs/archive/<YYYY-MM-DD>-<filename>
```

Use today's date as prefix.

### 5. Show summary

```
## Archived

Spec: specs/<filename>
Moved to: specs/archive/YYYY-MM-DD-<filename>
Tasks: N/N complete

Next: Run `safe-commit` if not already committed, or `ship` to create a PR.
```

---

## Guardrails

- Always confirm before archiving if tasks are incomplete
- Never archive with uncommitted changes — warn the user
- Preserve the original filename as a suffix (date prefix only)
- Do not delete the spec — archive is permanent history
