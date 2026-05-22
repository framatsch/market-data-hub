# market-data-hub - FastAPI data service for market and company data
# Copyright (C) 2026  Market Data Hub Contributors
#
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
"""Linting skill for Market Data Hub project.

Runs ruff check on app/, tests/, and scripts/.
Ensures code quality before commits and deployment.

Usage:
    python skills/lint_check.py --all
    python skills/lint_check.py --app
    python skills/lint_check.py --tests
    python skills/lint_check.py --fix  # Auto-fix issues
"""

import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


class LintResult:
    """Result of linting check."""

    def __init__(self, component: str, path: str, exit_code: int, output: str, errors: int = 0):
        self.component = component
        self.path = path
        self.exit_code = exit_code
        self.output = output
        self.errors = errors
        self.passed = exit_code == 0


def run_ruff_check(path: str, fix: bool = False) -> Tuple[int, str]:
    """Run ruff check on given path.

    Args:
        path: Path to check
        fix: Auto-fix issues if True

    Returns:
        Tuple of (exit_code, output)
    """
    cmd = ["ruff", "check", path]
    if fix:
        cmd.append("--fix")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 1, "ERROR: ruff not found. Install with: pip install ruff"


def count_errors(output: str) -> int:
    """Count number of errors in ruff output."""
    lines = output.strip().split('\n')
    error_count = 0
    for line in lines:
        if '.py:' in line and any(code in line for code in ['E', 'F', 'W', 'C', 'N']):
            error_count += 1
    return error_count


def check_app(fix: bool = False) -> LintResult:
    """Check main application code (app/)."""
    console.print("[yellow]Checking app/...[/yellow]")
    exit_code, output = run_ruff_check("app/", fix)
    errors = count_errors(output) if exit_code != 0 else 0
    return LintResult("Application", "app/", exit_code, output, errors)


def check_tests(fix: bool = False) -> LintResult:
    """Check test code (tests/)."""
    console.print("[yellow]Checking tests/...[/yellow]")
    exit_code, output = run_ruff_check("tests/", fix)
    errors = count_errors(output) if exit_code != 0 else 0
    return LintResult("Tests", "tests/", exit_code, output, errors)


def check_scripts(fix: bool = False) -> List[LintResult]:
    """Check diagnostic scripts (scripts/)."""
    console.print("[yellow]Checking scripts/diagnostics/...[/yellow]")

    scripts_dir = Path(__file__).parent.parent / "scripts" / "diagnostics"
    if not scripts_dir.exists():
        console.print("[dim]No diagnostic scripts found[/dim]")
        return []

    results = []
    # Scripts in diagnostics are excluded from CI (development-only)
    # But we can still check them optionally
    for script_file in scripts_dir.glob("*.py"):
        if script_file.name.startswith("_"):
            continue

        console.print(f"  → {script_file.name}")
        exit_code, output = run_ruff_check(str(script_file), fix)
        errors = count_errors(output) if exit_code != 0 else 0
        results.append(
            LintResult(
                f"Script: {script_file.name}",
                str(script_file),
                exit_code,
                output,
                errors
            )
        )

    return results


def print_results_table(results: List[LintResult]):
    """Print results in a nice table."""
    table = Table(title="🔍 Linting Results", show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=30)
    table.add_column("Status", justify="center", width=10)
    table.add_column("Errors", justify="right", width=10)

    for result in results:
        status = "✅ PASS" if result.passed else "❌ FAIL"
        status_style = "green" if result.passed else "red"
        table.add_row(
            result.component,
            f"[{status_style}]{status}[/{status_style}]",
            str(result.errors) if result.errors > 0 else "-"
        )

    console.print(table)


def print_error_details(results: List[LintResult]):
    """Print detailed error output for failed checks."""
    failed = [r for r in results if not r.passed]

    if not failed:
        return

    console.print("\n")
    console.print(Panel.fit("❌ Detailed Errors", style="red bold"))

    for result in failed:
        console.print(f"\n[red bold]{result.component}[/red bold] ({result.path}):")
        console.print(result.output)


@click.command()
@click.option('--all', 'check_all', is_flag=True, help='Check all components')
@click.option('--app', is_flag=True, help='Check app/ only')
@click.option('--tests', is_flag=True, help='Check tests/ only')
@click.option('--scripts', is_flag=True, help='Check scripts/diagnostics/ (optional)')
@click.option('--fix', is_flag=True, help='Auto-fix issues')
@click.option('--ci', is_flag=True, help='CI mode (exit 1 if any errors)')
def main(check_all: bool, app: bool, tests: bool, scripts: bool, fix: bool, ci: bool):
    """Run ruff linting checks on Market Data Hub components."""

    console.print(Panel.fit(
        "🔍 Market Data Hub - Linting Check\n"
        f"Auto-fix: {'[green]Enabled[/green]' if fix else '[dim]Disabled[/dim]'}",
        style="bold blue"
    ))

    # Default to --all if nothing specified (but exclude scripts)
    if not any([check_all, app, tests, scripts]):
        check_all = True

    results: List[LintResult] = []

    # Run checks
    if check_all or app:
        results.append(check_app(fix))

    if check_all or tests:
        results.append(check_tests(fix))

    if scripts:
        results.extend(check_scripts(fix))

    # Print results
    console.print("\n")
    print_results_table(results)

    # Print errors if any
    if any(not r.passed for r in results):
        print_error_details(results)
        console.print("\n[yellow]💡 Tip: Run with --fix to auto-fix some issues[/yellow]")
    else:
        console.print("\n[green bold]✨ All checks passed! Ready to commit.[/green bold]")

    # CI mode: exit with error if any failures
    if ci and any(not r.passed for r in results):
        console.print("\n[red]CI mode: Exiting with error code 1[/red]")
        sys.exit(1)

    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
