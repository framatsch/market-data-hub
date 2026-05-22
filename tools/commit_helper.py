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
"""Commit Helper — Generate and validate commits for the tradesensei project.

Analyzes git diff to suggest appropriate commit categories, validates messages,
and provides guided interactive commit creation.

Commit Format:
    [emoji] [Category]: [Specific Change]

    [Brief explanation]
    [Why it matters]

Categories:
    feat     ✨  New feature (maps to CHANGELOG: Added)
    fix      🔧  Bug fix (maps to CHANGELOG: Fixed)
    infra    📦  Docker, K8s, CI/CD changes
    db       🗄️  Alembic migrations, model changes
    api      🔌  FastAPI endpoint or schema changes
    frontend 🖥️  Next.js / React component changes
    test     🧪  Test additions or improvements
    docs     📝  Documentation, AGENTS.md, OpenAPI
    config   ⚙️  Environment, settings, pyproject.toml
    security 🔒  Auth, JWT, permissions, secrets
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

console = Console()

CATEGORIES: Dict[str, Dict] = {
    "feat": {
        "emoji": "✨",
        "patterns": [
            "app/api/",
            "app/services/",
            "app/schemas/",
            "components/",
            "app/(",
        ],
        "description": "New feature implementation",
        "changelog": "Added",
    },
    "fix": {
        "emoji": "🔧",
        "patterns": ["fix", "bug", "error", "incorrect", "wrong"],
        "description": "Bug fix in any layer",
        "changelog": "Fixed",
    },
    "infra": {
        "emoji": "📦",
        "patterns": [
            "Dockerfile",
            "docker-compose",
            "k8s/",
            ".github/workflows",
            "ci.yml",
            "docker.yml",
        ],
        "description": "Docker, Kubernetes, or CI/CD",
        "changelog": "Changed",
    },
    "db": {
        "emoji": "🗄️",
        "patterns": ["alembic/", "app/models/", "migrations/", "hypertable"],
        "description": "Database model or migration",
        "changelog": "Changed",
    },
    "api": {
        "emoji": "🔌",
        "patterns": ["app/api/", "app/schemas/", "app/repositories/", "app/services/"],
        "description": "FastAPI endpoint or schema change",
        "changelog": "Added",
    },
    "frontend": {
        "emoji": "🖥️",
        "patterns": [
            "frontend/",
            "components/",
            "app/(dashboard)",
            "hooks/",
            "stores/",
        ],
        "description": "Next.js / React component",
        "changelog": "Added",
    },
    "test": {
        "emoji": "🧪",
        "patterns": ["tests/", "test_", "conftest", "pytest", "coverage"],
        "description": "Test additions or improvements",
        "changelog": "Changed",
    },
    "docs": {
        "emoji": "📝",
        "patterns": [".md", "AGENTS.md", "CHANGELOG", "docs/", "openapi", "docstring"],
        "description": "Documentation update",
        "changelog": "Changed",
    },
    "config": {
        "emoji": "⚙️",
        "patterns": [
            "pyproject.toml",
            ".env",
            "config",
            "settings",
            "uv.lock",
            "opencode.json",
        ],
        "description": "Configuration or dependency change",
        "changelog": "Changed",
    },
    "security": {
        "emoji": "🔒",
        "patterns": ["auth", "jwt", "password", "secret", "permission", "token"],
        "description": "Security, auth, or permissions",
        "changelog": "Security",
    },
}


def run_git_command(args: List[str]) -> Tuple[int, str, str]:
    """Run a git command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def get_git_status() -> Dict[str, List[str]]:
    """Get lists of modified, added, and deleted files."""
    exit_code, stdout, _ = run_git_command(["status", "--short"])
    if exit_code != 0:
        return {"modified": [], "added": [], "deleted": []}

    status: Dict[str, List[str]] = {"modified": [], "added": [], "deleted": []}
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        code = line[:2].strip()
        filepath = line[3:]
        if code in ("M", "MM"):
            status["modified"].append(filepath)
        elif code in ("A", "AM", "??"):
            status["added"].append(filepath)
        elif code == "D":
            status["deleted"].append(filepath)
    return status


def get_git_diff() -> str:
    """Return staged diff, falling back to unstaged diff."""
    _, stdout, _ = run_git_command(["diff", "--staged"])
    if not stdout:
        _, stdout, _ = run_git_command(["diff"])
    return stdout


def suggest_category(status: Dict[str, List[str]], diff: str) -> str:
    """Suggest the most fitting commit category based on changed files."""
    all_text = (
        " ".join(status["modified"] + status["added"] + status["deleted"]) + " " + diff
    )

    scores: Dict[str, int] = {}
    for category, info in CATEGORIES.items():
        score = sum(1 for pattern in info["patterns"] if pattern in all_text)
        if score > 0:
            scores[category] = score

    return max(scores, key=lambda k: scores[k]) if scores else "docs"


def validate_commit_message(message: str) -> Tuple[bool, List[str]]:
    """Validate commit message format. Returns (is_valid, issues)."""
    issues: List[str] = []
    lines = message.split("\n")

    if not lines or not lines[0].strip():
        return False, ["Empty commit message"]

    first_line = lines[0]

    if ":" not in first_line:
        issues.append("Missing ':' separator — expected '[emoji] [category]: [title]'")

    has_emoji = any(info["emoji"] in first_line for info in CATEGORIES.values())
    if not has_emoji:
        issues.append("Missing emoji at start of commit message")

    if len(first_line) < 10:
        issues.append("Commit message too short (< 10 characters)")
    if len(first_line) > 100:
        issues.append("Commit message too long (> 100 characters)")

    return len(issues) == 0, issues


def ensure_license_header(files: List[str]) -> None:
    """Ensure that modified or added files contain the AGPLv3 license header."""
    PYTHON_HEADER = """# This program is free software: you can redistribute it and/or modify
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

"""
    JS_HEADER = """/*
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

"""
    import os
    for file in files:
        if not os.path.exists(file):
            continue
        ext = os.path.splitext(file)[1]
        try:
            if ext == '.py':
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                if "GNU Affero General Public License" not in content:
                    with open(file, 'w', encoding='utf-8') as f:
                        f.write(PYTHON_HEADER + content)
                    console.print(f"[yellow]Added AGPLv3 header to {file}[/yellow]")
            elif ext in ['.ts', '.tsx', '.js', '.jsx']:
                with open(file, 'r', encoding='utf-8') as f:
                    content = f.read()
                if "GNU Affero General Public License" not in content:
                    with open(file, 'w', encoding='utf-8') as f:
                        f.write(JS_HEADER + content)
                    console.print(f"[yellow]Added AGPLv3 header to {file}[/yellow]")
        except Exception as e:
            console.print(f"[red]Failed to check/add license to {file}: {e}[/red]")

def format_commit_message(
    category: str, title: str, explanation: str = "", why: str = ""
) -> str:
    """Format a commit message according to project standards."""
    emoji = CATEGORIES[category]["emoji"]
    message = f"{emoji} {category}: {title}"
    if explanation:
        message += f"\n\n{explanation}"
    if why:
        message += f"\n{why}"
    return message


def commit_with_message(message: str, add_all: bool = False) -> bool:
    """Stage all files (if requested) and create the commit."""
    if add_all:
        code, _, stderr = run_git_command(["add", "-A"])
        if code != 0:
            console.print(f"[red]Failed to stage files: {stderr}[/red]")
            return False

    code, _, stderr = run_git_command(["commit", "-m", message])
    if code != 0:
        console.print(f"[red]Commit failed: {stderr}[/red]")
        return False
    return True


@click.command()
@click.option("--validate", is_flag=True, help="Validate the last commit message")
@click.option("--auto", is_flag=True, help="Auto-suggest category from diff")
@click.option(
    "--preview", is_flag=True, help="Preview commit message without committing"
)
@click.option("--add-all", is_flag=True, help="Run 'git add -A' before committing")
def main(validate: bool, auto: bool, preview: bool, add_all: bool) -> None:
    """Trade Sensei — Commit Helper."""
    console.print(
        Panel.fit(
            "[bold cyan]Trade Sensei — Commit Helper[/bold cyan]\n"
            "Consistent commits following Keep a Changelog categories",
            border_style="cyan",
        )
    )

    if validate:
        _, last_commit, _ = run_git_command(["log", "-1", "--pretty=%B"])
        if not last_commit.strip():
            console.print("[red]No commits found[/red]")
            sys.exit(1)
        console.print(
            Panel(last_commit.strip(), title="Last Commit", border_style="blue")
        )
        is_valid, issues = validate_commit_message(last_commit.strip())
        if is_valid:
            console.print("[green]✓ Commit message is valid[/green]")
        else:
            console.print("[red]Commit message has issues:[/red]")
            for issue in issues:
                console.print(f"  • {issue}")
            sys.exit(1)
        return

    status = get_git_status()
    all_files = status["modified"] + status["added"] + status["deleted"]
    if not all_files:
        console.print("[yellow]No changes detected[/yellow]")
        sys.exit(0)

    # Check and add licenses early so they are included in the diff
    ensure_license_header(status["modified"] + status["added"])
    if not preview:
        run_git_command(["add", "-A"]) # Automatically stage the headers if any were added
        status = get_git_status() # Re-evaluate status

    table = Table(title="Changed Files", border_style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("File")
    for f in status["modified"]:
        table.add_row("[yellow]Modified[/yellow]", f)
    for f in status["added"]:
        table.add_row("[green]Added[/green]", f)
    for f in status["deleted"]:
        table.add_row("[red]Deleted[/red]", f)
    console.print(table)

    diff = get_git_diff()
    suggested = suggest_category(status, diff)

    console.print(
        f"\n[bold]Suggested:[/bold] {CATEGORIES[suggested]['emoji']} {suggested} "
        f"— {CATEGORIES[suggested]['description']}"
    )

    if not auto:
        console.print("\n[bold]All categories:[/bold]")
        for i, (cat, info) in enumerate(CATEGORIES.items(), 1):
            marker = "→" if cat == suggested else " "
            console.print(f"{marker} {i}. {info['emoji']} {cat}: {info['description']}")

        choice = Prompt.ask(
            "\n[bold cyan]Select category[/bold cyan]",
            choices=[str(i) for i in range(1, len(CATEGORIES) + 1)],
            default=str(list(CATEGORIES.keys()).index(suggested) + 1),
        )
        suggested = list(CATEGORIES.keys())[int(choice) - 1]

    title = Prompt.ask("\n[bold cyan]Commit title[/bold cyan]")
    explanation = Prompt.ask(
        "[bold cyan]Brief explanation[/bold cyan] (optional)", default=""
    )
    why = Prompt.ask("[bold cyan]Why it matters[/bold cyan] (optional)", default="")

    commit_message = format_commit_message(suggested, title, explanation, why)
    console.print("\n[bold]Commit message:[/bold]")
    console.print(Panel(commit_message, border_style="green"))

    is_valid, issues = validate_commit_message(commit_message)
    if not is_valid:
        for issue in issues:
            console.print(f"[yellow]  ⚠ {issue}[/yellow]")

    if preview:
        sys.exit(0)

    if Confirm.ask("Create commit?", default=True):
        if commit_with_message(commit_message, add_all):
            console.print("[green]✓ Commit created[/green]")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
