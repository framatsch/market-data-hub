#!/usr/bin/env python3
"""Commit Helper - Generate and validate commits according to Market Data Hub standards.

This skill helps maintain consistent commit message formatting by:
- Analyzing git diff to suggest appropriate commit categories
- Validating commit messages against project standards
- Providing interactive guided commit creation
- Supporting batch commits for multiple logical changes

Commit Format:
    [emoji] [Category]: [Specific Change]

    [Brief explanation]
    [Impact on API/Provider if relevant]

Categories:
    🔧 Fix: Bug fixes
    ✨ Add: New features
    📚 Docs: Documentation
    🔄 Refactor: Code reorganization
    ⚡ Perf: Performance improvements
    🐛 Debug: Debugging changes
    🔌 Provider: Provider-specific changes (IBKR/LSEG)
    🌐 API: API endpoint changes
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

# Category definitions with emojis and detection patterns
CATEGORIES = {
    "Fix": {
        "emoji": "🔧",
        "patterns": ["fix", "bug", "error", "correct", "handle"],
        "description": "Bug fixes",
    },
    "Add": {
        "emoji": "✨",
        "patterns": ["add", "new", "feature", "implement", "create"],
        "description": "New features",
    },
    "Docs": {
        "emoji": "📚",
        "patterns": [".md", "doc/", "README", "documentation", "copilot"],
        "description": "Documentation",
    },
    "Refactor": {
        "emoji": "🔄",
        "patterns": ["refactor", "reorganize", "restructure", "clean"],
        "description": "Code reorganization",
    },
    "Perf": {
        "emoji": "⚡",
        "patterns": ["performance", "optimize", "speed", "cache"],
        "description": "Performance improvements",
    },
    "Debug": {
        "emoji": "🐛",
        "patterns": ["debug", "logging", "trace"],
        "description": "Debugging changes",
    },
    "Provider": {
        "emoji": "🔌",
        "patterns": ["providers/", "ibkr", "lseg", "finnhub", "contract", "session"],
        "description": "Provider-specific changes (IBKR/LSEG)",
    },
    "API": {
        "emoji": "🌐",
        "patterns": ["routes_", "api/", "endpoint", "router", "fastapi"],
        "description": "API endpoint changes",
    },
}


def run_git_command(args: List[str]) -> Tuple[int, str, str]:
    """Run git command and return exit code, stdout, stderr."""
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
    """Get modified, added, and deleted files from git status."""
    exit_code, stdout, _ = run_git_command(["status", "--short"])
    if exit_code != 0:
        return {"modified": [], "added": [], "deleted": []}

    status = {"modified": [], "added": [], "deleted": []}
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        status_code = line[:2].strip()
        filepath = line[3:]

        if status_code in ["M", "MM"]:
            status["modified"].append(filepath)
        elif status_code in ["A", "AM", "??"]:
            status["added"].append(filepath)
        elif status_code == "D":
            status["deleted"].append(filepath)

    return status


def get_git_diff() -> str:
    """Get git diff output."""
    exit_code, stdout, _ = run_git_command(["diff", "--staged"])
    if exit_code != 0 or not stdout:
        exit_code, stdout, _ = run_git_command(["diff"])
    return stdout


def suggest_category(status: Dict[str, List[str]], diff: str) -> str:
    """Suggest commit category based on changed files and diff content."""
    all_files = status["modified"] + status["added"] + status["deleted"]
    all_text = " ".join(all_files) + " " + diff

    scores = {}
    for category, info in CATEGORIES.items():
        score = sum(1 for pattern in info["patterns"] if pattern in all_text)
        if score > 0:
            scores[category] = score

    if not scores:
        return "Doc"  # Default fallback

    # Return category with highest score
    return max(scores.items(), key=lambda x: x[1])[0]


def validate_commit_message(message: str) -> Tuple[bool, List[str]]:
    """Validate commit message format.

    Returns:
        (is_valid, list_of_issues)
    """
    issues = []
    lines = message.split("\n")

    if not lines:
        return False, ["Empty commit message"]

    # Check first line format: [emoji] [Category]: [Message]
    first_line = lines[0]
    if ":" not in first_line:
        issues.append("Missing ':' separator in first line")

    # Check for emoji
    found_emoji = False
    for category, info in CATEGORIES.items():
        if info["emoji"] in first_line:
            found_emoji = True
            if category not in first_line:
                issues.append(f"Emoji {info['emoji']} present but category '{category}' not found")
            break

    if not found_emoji:
        issues.append("Missing emoji at start of commit message")

    # Check if message is too short
    if len(first_line) < 10:
        issues.append("Commit message too short (< 10 chars)")

    # Check if message is too long
    if len(first_line) > 100:
        issues.append("Commit message too long (> 100 chars)")

    return len(issues) == 0, issues


def get_last_commit_message() -> Optional[str]:
    """Get the last commit message."""
    exit_code, stdout, _ = run_git_command(["log", "-1", "--pretty=%B"])
    if exit_code != 0:
        return None
    return stdout.strip()


def format_commit_message(category: str, title: str, explanation: str = "", why: str = "") -> str:
    """Format commit message according to standards."""
    emoji = CATEGORIES[category]["emoji"]
    message = f"{emoji} {category}: {title}"

    if explanation:
        message += f"\n\n{explanation}"
    if why:
        message += f"\n{why}"

    return message


def commit_with_message(message: str, add_all: bool = False) -> bool:
    """Create commit with given message."""
    if add_all:
        exit_code, _, stderr = run_git_command(["add", "-A"])
        if exit_code != 0:
            console.print(f"[red]Failed to add files: {stderr}[/red]")
            return False

    exit_code, _, stderr = run_git_command(["commit", "-m", message])
    if exit_code != 0:
        console.print(f"[red]Commit failed: {stderr}[/red]")
        return False

    return True


@click.command()
@click.option("--validate", is_flag=True, help="Validate last commit message")
@click.option("--auto", is_flag=True, help="Auto-generate commit from git diff")
@click.option("--preview", is_flag=True, help="Preview commit without creating it")
@click.option("--add-all", is_flag=True, help="Run 'git add -A' before commit")
def main(validate: bool, auto: bool, preview: bool, add_all: bool):
    """Market Data Hub Commit Helper - Generate and validate commits."""

    console.print(
        Panel.fit(
            "[bold cyan]🤖 Market Data Hub - Commit Helper[/bold cyan]\n"
            "Generate and validate commits according to project standards",
            border_style="cyan",
        )
    )

    # Mode: Validate last commit
    if validate:
        last_commit = get_last_commit_message()
        if not last_commit:
            console.print("[red]❌ No commits found[/red]")
            sys.exit(1)

        console.print("\n[bold]Last Commit:[/bold]")
        console.print(Panel(last_commit, border_style="blue"))

        is_valid, issues = validate_commit_message(last_commit)
        if is_valid:
            console.print("[green]✅ Commit message is valid[/green]")
            sys.exit(0)
        else:
            console.print("[red]❌ Commit message has issues:[/red]")
            for issue in issues:
                console.print(f"  • {issue}")
            sys.exit(1)

    # Get git status
    status = get_git_status()
    all_files = status["modified"] + status["added"] + status["deleted"]

    if not all_files:
        console.print("[yellow]⚠️  No changes detected[/yellow]")
        sys.exit(0)

    # Show changed files
    table = Table(title="Changed Files", border_style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("File")

    for file in status["modified"]:
        table.add_row("[yellow]Modified[/yellow]", file)
    for file in status["added"]:
        table.add_row("[green]Added[/green]", file)
    for file in status["deleted"]:
        table.add_row("[red]Deleted[/red]", file)

    console.print(table)

    # Mode: Auto-generate
    if auto:
        diff = get_git_diff()
        suggested_category = suggest_category(status, diff)

        console.print(f"\n[bold]Suggested Category:[/bold] {CATEGORIES[suggested_category]['emoji']} {suggested_category}")
        console.print(f"[dim]{CATEGORIES[suggested_category]['description']}[/dim]")

        title = Prompt.ask("\n[bold cyan]Commit title[/bold cyan]")
        explanation = Prompt.ask("[bold cyan]Brief explanation[/bold cyan] (optional)", default="")
        why = Prompt.ask("[bold cyan]Why it matters[/bold cyan] (optional)", default="")

        commit_message = format_commit_message(suggested_category, title, explanation, why)

        console.print("\n[bold]Generated Commit Message:[/bold]")
        console.print(Panel(commit_message, border_style="green"))

        if preview:
            sys.exit(0)

        if Confirm.ask("Create commit?", default=True):
            if commit_with_message(commit_message, add_all):
                console.print("[green]✅ Commit created successfully[/green]")
                sys.exit(0)
            else:
                sys.exit(1)
        else:
            console.print("[yellow]Commit cancelled[/yellow]")
            sys.exit(0)

    # Mode: Guided (interactive)
    diff = get_git_diff()
    suggested_category = suggest_category(status, diff)

    console.print(f"\n[bold]Suggested Category:[/bold] {CATEGORIES[suggested_category]['emoji']} {suggested_category}")

    # Show all categories
    console.print("\n[bold]Available Categories:[/bold]")
    for i, (category, info) in enumerate(CATEGORIES.items(), 1):
        marker = "→" if category == suggested_category else " "
        console.print(f"{marker} {i}. {info['emoji']} {category}: {info['description']}")

    # Select category
    category_choice = Prompt.ask(
        "\n[bold cyan]Select category[/bold cyan]",
        choices=[str(i) for i in range(1, len(CATEGORIES) + 1)],
        default=str(list(CATEGORIES.keys()).index(suggested_category) + 1),
    )
    selected_category = list(CATEGORIES.keys())[int(category_choice) - 1]

    # Get commit details
    title = Prompt.ask("\n[bold cyan]Commit title[/bold cyan]")
    explanation = Prompt.ask("[bold cyan]Brief explanation[/bold cyan] (optional)", default="")
    why = Prompt.ask("[bold cyan]Why it matters[/bold cyan] (optional)", default="")

    commit_message = format_commit_message(selected_category, title, explanation, why)

    console.print("\n[bold]Generated Commit Message:[/bold]")
    console.print(Panel(commit_message, border_style="green"))

    # Validate before commit
    is_valid, issues = validate_commit_message(commit_message)
    if not is_valid:
        console.print("[yellow]⚠️  Validation warnings:[/yellow]")
        for issue in issues:
            console.print(f"  • {issue}")

    if preview:
        sys.exit(0)

    if Confirm.ask("Create commit?", default=True):
        if commit_with_message(commit_message, add_all):
            console.print("[green]✅ Commit created successfully[/green]")
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        console.print("[yellow]Commit cancelled[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
