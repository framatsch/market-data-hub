# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import tempfile
import argparse
from datetime import datetime


def get_git_hash():
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.STDOUT
            )
            .decode("utf-8")
            .strip()
        )
    except:
        return None


def update_json_file(file_path, new_version):
    if not os.path.exists(file_path):
        return False
    with open(file_path, "r") as f:
        data = json.load(f)
    data["version"] = new_version
    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return True


def update_toml_file(file_path, new_version):
    if not os.path.exists(file_path):
        return False
    with open(file_path, "r") as f:
        content = f.read()

    # Replace version = "..." with version = "new_version"
    new_content = re.sub(
        r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', content, count=1
    )

    if new_content == content:
        return False

    with open(file_path, "w") as f:
        f.write(new_content)
    return True


def main():
    parser = argparse.ArgumentParser(description="Bump version in project files")
    parser.add_argument("version", help="The version to set (e.g., 0.5.0)")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Add .dev0 suffix for development versions",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help="Commit the bump, create a git tag and push to origin (requires git/gh)",
    )
    parser.add_argument(
        "--gh-release",
        action="store_true",
        help="Create a GitHub release using the 'gh' CLI after pushing the tag",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Assume yes for confirmations when performing release actions",
    )
    parser.add_argument(
        "--notes",
        help="Inline release notes text (if provided, used for GitHub release)",
    )
    args = parser.parse_args()

    version = args.version
    if args.snapshot:
        # PEP 440: only append .dev0 if the version doesn't already end with it
        if not version.endswith(".dev0"):
            version += ".dev0"

    # Files to update
    json_files = ["package.json", "frontend/package.json"]
    toml_files = ["backend/pyproject.toml"]

    updated = []
    for f in json_files:
        if update_json_file(f, version):
            updated.append(f)

    for f in toml_files:
        if update_toml_file(f, version):
            updated.append(f)

    if updated:
        print(f"Successfully bumped version to {version} in: {', '.join(updated)}")
        # Prepare git command for the user
        print(f"\nNext steps:")
        print(f"git add {' '.join(updated)}")
        print(f'git commit -m "📦 config: bump version to {version}"')
        changelog_updated = False

        def prepare_release_notes_from_changelog(version: str) -> str | None:
            changelog_path = "CHANGELOG.md"
            if not os.path.exists(changelog_path):
                return None
            with open(changelog_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Find Unreleased section
            start_idx = None
            for i, ln in enumerate(lines):
                if ln.strip() == "## [Unreleased]":
                    start_idx = i
                    break
            if start_idx is None:
                return None

            # Find next '## [' after start_idx
            end_idx = None
            for j in range(start_idx + 1, len(lines)):
                if lines[j].startswith("## ["):
                    end_idx = j
                    break
            if end_idx is None:
                end_idx = len(lines)

            # Extract unreleased content
            unreleased_lines = [l.rstrip("\n") for l in lines[start_idx + 1 : end_idx]]
            # Trim leading/trailing blank lines
            while unreleased_lines and unreleased_lines[0].strip() == "":
                unreleased_lines.pop(0)
            while unreleased_lines and unreleased_lines[-1].strip() == "":
                unreleased_lines.pop()

            if not unreleased_lines:
                return None

            # Build new version section
            today = datetime.utcnow().strftime("%Y-%m-%d")
            new_section = [f"## [{args.version}] - {today}\n", "\n"]
            new_section += [l + "\n" for l in unreleased_lines]
            new_section += ["\n"]

            # Insert new_section after Unreleased header
            new_lines = lines[: start_idx + 1] + ["\n"] + new_section + lines[end_idx:]

            # Update reference links at the bottom if possible
            try:
                # Get previous tag
                prev_tag = (
                    subprocess.check_output(
                        ["git", "describe", "--tags", "--abbrev=0"],
                        stderr=subprocess.DEVNULL,
                    )
                    .decode()
                    .strip()
                )
            except Exception:
                prev_tag = None

            repo_url = None
            try:
                remote = (
                    subprocess.check_output(["git", "remote", "get-url", "origin"])
                    .decode()
                    .strip()
                )
                # Convert git@github.com:owner/repo.git or https url to https://github.com/owner/repo
                if remote.startswith("git@github.com:"):
                    repo_path = remote.split(":", 1)[1]
                    repo_url = f"https://github.com/{repo_path.replace('.git', '')}"
                elif remote.startswith("https://"):
                    repo_url = remote.replace(".git", "")
                else:
                    repo_url = None
            except Exception:
                repo_url = None

            # Add reference link for the new version and update [unreleased]
            if repo_url and prev_tag:
                compare_line = f"[{args.version}]: {repo_url}/compare/{prev_tag}...v{args.version}\n"
                # Find position of reference block (lines starting with '[' near end)
                ref_start = None
                for i in range(len(new_lines) - 1, -1, -1):
                    if new_lines[i].startswith("["):
                        ref_start = i
                if ref_start is None:
                    new_lines.append("\n")
                    new_lines.append(compare_line)
                else:
                    # Insert new compare_line before existing references
                    new_lines = (
                        new_lines[:ref_start] + [compare_line] + new_lines[ref_start:]
                    )

                # Update [unreleased] reference to compare from this new tag to HEAD
                for k in range(len(new_lines)):
                    if new_lines[k].lower().startswith("[unreleased]:"):
                        new_lines[k] = (
                            f"[unreleased]: {repo_url}/compare/v{args.version}...HEAD\n"
                        )

            # Write back the changelog
            with open(changelog_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            return "\n".join(unreleased_lines) + "\n"

        release_notes = None
        # Only try to prepare changelog if user requested a GH release or release
        if args.release:
            release_notes = prepare_release_notes_from_changelog(args.version)
            if release_notes:
                changelog_updated = True
                # Ensure CHANGELOG.md is added to the list to commit
                if "CHANGELOG.md" not in updated:
                    updated.append("CHANGELOG.md")
        # If user requested a release, perform commit/tag/push (interactive unless --yes)
        if args.release:
            # Commit changes
            try:
                subprocess.check_call(["git", "add"] + updated)
                subprocess.check_call(
                    [
                        "git",
                        "commit",
                        "-m",
                        f"📦 config: bump version to {version}",
                    ]
                )
            except subprocess.CalledProcessError as e:
                print("Failed to commit version bump:", e)
                sys.exit(1)

            # Determine tag name from the raw version argument (use original user-specified version)
            tag_name = f"v{args.version}"

            # Confirm with user before pushing unless --yes
            if not args.yes:
                ans = input(
                    f"About to create tag '{tag_name}' and push to origin. Continue? [y/N]: "
                )
                if ans.lower() != "y":
                    print("Aborted by user.")
                    sys.exit(0)

            # Create annotated tag and push
            try:
                subprocess.check_call(["git", "tag", "-a", tag_name, "-m", tag_name])
                subprocess.check_call(["git", "push", "origin", "HEAD"])
                subprocess.check_call(["git", "push", "origin", tag_name])
            except subprocess.CalledProcessError as e:
                print("Failed to create/push tag:", e)
                sys.exit(1)

            # Optionally create a GitHub release using gh
            if args.gh_release:
                # Prepare notes file
                notes_file = None
                try:
                    if args.notes:
                        tf = tempfile.NamedTemporaryFile(mode="w", delete=False)
                        tf.write(args.notes)
                        tf.flush()
                        notes_file = tf.name
                        tf.close()
                    elif release_notes:
                        tf = tempfile.NamedTemporaryFile(mode="w", delete=False)
                        tf.write(release_notes)
                        tf.flush()
                        notes_file = tf.name
                        tf.close()
                    else:
                        # default minimal notes
                        tf = tempfile.NamedTemporaryFile(mode="w", delete=False)
                        tf.write(f"Release {tag_name}\n")
                        tf.flush()
                        notes_file = tf.name
                        tf.close()

                    # Create release
                    subprocess.check_call(
                        [
                            "gh",
                            "release",
                            "create",
                            tag_name,
                            "--title",
                            tag_name,
                            "--notes-file",
                            notes_file,
                        ]
                    )
                    print(f"GitHub release {tag_name} created.")
                except subprocess.CalledProcessError as e:
                    print("Failed to create GitHub release:", e)
                    sys.exit(1)
                finally:
                    if notes_file and os.path.exists(notes_file):
                        try:
                            os.remove(notes_file)
                        except Exception:
                            pass
    else:
        print("No files were updated.")
        sys.exit(1)


if __name__ == "__main__":
    main()
