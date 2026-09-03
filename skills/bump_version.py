#!/usr/bin/env python3
"""
Bump version script for market-data-hub.
Updates pyproject.toml, updates CHANGELOG.md, runs tests, and creates a git tag.
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        print(f"Error running {' '.join(cmd)}")
        sys.exit(1)
    return result


def get_current_version() -> str:
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("Error: pyproject.toml not found")
        sys.exit(1)

    with open(pyproject_path, "r", encoding="utf-8") as f:
        content = f.read()

    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        return match.group(1)
    
    print("Error: Could not find version in pyproject.toml")
    sys.exit(1)


def update_version(new_version: str) -> None:
    pyproject_path = Path("pyproject.toml")
    with open(pyproject_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = re.sub(
        r'^version\s*=\s*"([^"]+)"',
        f'version = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE
    )

    with open(pyproject_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Update frontend version
    print("\n--- Updating Admin UI Version ---")
    subprocess.run(["npm", "version", new_version, "--no-git-tag-version", "--allow-same-version"], cwd="admin", check=True)


def update_changelog(new_version: str) -> None:
    changelog_path = Path("CHANGELOG.md")
    if not changelog_path.exists():
        print("CHANGELOG.md not found, skipping...")
        return

    with open(changelog_path, "r", encoding="utf-8") as f:
        content = f.read()

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    unreleased_header = "## [Unreleased]"
    new_header = f"## [Unreleased]\n\n## [{new_version}] - {today}"

    if unreleased_header in content:
        new_content = content.replace(unreleased_header, new_header, 1)
        with open(changelog_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("Updated CHANGELOG.md")
    else:
        print("Warning: '## [Unreleased]' section not found in CHANGELOG.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump project version, run tests, and create git tag.")
    parser.add_argument("new_version", help="The new version (e.g., 0.2.0)")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running tests and linter")
    args = parser.parse_args()

    new_version = args.new_version
    if new_version.startswith("v"):
        new_version = new_version[1:]

    # 1. Check working directory
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if status.stdout.strip():
        print("Error: Git working directory is not clean. Commit or stash changes first.")
        sys.exit(1)

    # 2. Run quality checks
    if not args.skip_tests:
        print("\n--- Running Linter ---")
        run_cmd(["uv", "run", "ruff", "check", "app/"])
        print("\n--- Running Tests ---")
        run_cmd(["uv", "run", "pytest", "--maxfail=1", "--disable-warnings"])

    # 3. Update files
    old_version = get_current_version()
    print(f"\n--- Bumping version: {old_version} -> {new_version} ---")
    update_version(new_version)
    update_changelog(new_version)

    # 4. Commit and Tag
    print("\n--- Creating Git Commit and Tag ---")
    run_cmd(["git", "add", "pyproject.toml", "CHANGELOG.md", "admin/package.json", "admin/package-lock.json"])
    commit_msg = f"⚙️ config: bump version to {new_version}"
    run_cmd(["git", "commit", "-m", commit_msg])
    run_cmd(["git", "tag", "-a", f"v{new_version}", "-m", f"v{new_version}"])

    print(f"\n✅ Successfully bumped version to v{new_version} and created local tag.")
    print("\n--- Pushing to GitHub and Creating Release ---")
    run_cmd(["git", "push", "origin", "main"])
    run_cmd(["git", "push", "origin", f"v{new_version}"])
    run_cmd(["gh", "release", "create", f"v{new_version}", "--title", f"v{new_version}", "--generate-notes"])
    print(f"\n🎉 Release v{new_version} published! Discord notification should trigger shortly.")


if __name__ == "__main__":
    main()
