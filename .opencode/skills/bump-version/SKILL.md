---
name: bump-version
description: Bump the version in pyproject.toml, tag the release, and push to GHCR via CI. Use when the user asks to "create release version X.Y.Z" or "bump version".
license: MIT
compatibility: opencode
metadata:
  toolchain: python, git, gh
---

## What I do

Bump the version in `pyproject.toml`, commit, tag, push — triggering the CI pipeline which builds and pushes the Docker image to GHCR automatically.

## Version file

Single source of truth: `pyproject.toml` → `[project] version = "X.Y.Z"`

No `package.json`, no frontend, no separate backend directory. One file only.

## Workflow: Creating a Release

When the user asks to "create release version X.Y.Z":

1. **Check current version**
   ```bash
   grep '^version' pyproject.toml
   git describe --tags --abbrev=0
   ```

2. **Edit pyproject.toml**
   Update `version = "X.Y.Z"` under `[project]`.

3. **Lint + test before tagging**
   ```bash
   uv run ruff check app/
   uv run pytest --maxfail=1 --disable-warnings
   ```
   Do not tag if either fails.

4. **Commit the bump**
   ```bash
   git add pyproject.toml
   python skills/commit_helper.py --preview
   # Use: ⚙️ config: bump version to X.Y.Z
   git commit -m "⚙️ config: bump version to X.Y.Z"
   ```

5. **Tag and push — CI handles the rest**
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main vX.Y.Z
   ```
   CI (`.github/workflows/ci.yml`) triggers on `v*` tags: runs lint → test → builds Docker image → pushes to GHCR with semver tags (`X.Y.Z`, `X.Y`, `X`).

6. **Create GitHub Release (optional)**
   ```bash
   cat > /tmp/release_notes.md << 'HEREDOC'
   ## vX.Y.Z

   ### Changed
   - Describe changes here
   HEREDOC
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/release_notes.md
   rm /tmp/release_notes.md
   ```
   If `CHANGELOG.md` has an `## [Unreleased]` section, use its content as release notes.

## Guardrails

- Version must follow Semantic Versioning (`X.Y.Z`).
- Only one file to update: `pyproject.toml`.
- Never tag if lint or tests fail.
- Never commit without explicit user approval.
- GHCR push happens automatically via CI — do not push Docker images manually.
