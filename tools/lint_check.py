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
"""Linting and type-check runner for the Market Data Hub application.

Runs ruff and mypy on the application via uv.

Usage:
    python tools/lint_check.py            # Run everything
    python tools/lint_check.py --ruff     # Ruff only
    python tools/lint_check.py --mypy     # mypy only
    python tools/lint_check.py --fix      # Auto-fix ruff issues
    python tools/lint_check.py --ci       # Exit 1 on any failure (CI mode)
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

ROOT_DIR = Path(__file__).parent.parent
BACKEND_DIR = ROOT_DIR


class CheckResult:
    """Result of a single linting/type-check run."""

    def __init__(self, name: str, exit_code: int, output: str) -> None:
        self.name = name
        self.exit_code = exit_code
        self.output = output
        self.passed = exit_code == 0


def run_uv(args: List[str]) -> Tuple[int, str]:
    """Run a command via uv."""
    try:
        result = subprocess.run(
            ["uv", "run"] + args,
            capture_output=True,
            text=True,
            check=False,
            cwd=BACKEND_DIR,
        )
        return result.returncode, result.stdout + result.stderr
    except FileNotFoundError:
        return 1, "ERROR: uv not found. Install from https://docs.astral.sh/uv/"


def run_ruff_check(fix: bool = False) -> CheckResult:
    """Run ruff check on the app directory."""
    console.print("[yellow]Running ruff check...[/yellow]")
    args = ["ruff", "check", "app/"]
    if fix:
        args.append("--fix")
    code, output = run_uv(args)
    return CheckResult("ruff check", code, output)


def run_ruff_format(fix: bool = False) -> CheckResult:
    """Run ruff format on the app directory."""
    console.print("[yellow]Running ruff format...[/yellow]")
    args = ["ruff", "format", "app/"]
    if not fix:
        args.append("--check")
    code, output = run_uv(args)
    return CheckResult("ruff format", code, output)


def run_mypy() -> CheckResult:
    """Run mypy strict on the app directory."""
    console.print("[yellow]Running mypy --strict...[/yellow]")
    code, output = run_uv(["mypy", "--strict", "app/"])
    return CheckResult("mypy --strict", code, output)


def print_summary(results: List[CheckResult]) -> None:
    """Print a summary table of all check results."""
    table = Table(title="Lint Results", show_header=True, header_style="bold magenta")
    table.add_column("Check", style="cyan", width=20)
    table.add_column("Status", justify="center", width=12)

    for r in results:
        status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
        table.add_row(r.name, status)

    console.print(table)

    for r in results:
        if not r.passed and r.output.strip():
            console.print(f"\n[red bold]{r.name} output:[/red bold]")
            console.print(r.output)


@click.command()
@click.option("--ruff", "ruff_only", is_flag=True, help="Run ruff check + format only")
@click.option("--mypy", "mypy_only", is_flag=True, help="Run mypy only")
@click.option("--fix", is_flag=True, help="Auto-fix ruff issues")
@click.option("--ci", is_flag=True, help="Exit 1 if any check fails (for CI)")
def main(ruff_only: bool, mypy_only: bool, fix: bool, ci: bool) -> None:
    """Run linting and type checks on the Market Data Hub application."""
    if not BACKEND_DIR.exists():
        console.print(f"[red]Application directory not found: {BACKEND_DIR}[/red]")
        sys.exit(1)

    console.print(
        Panel.fit(
            "[bold blue]Market Data Hub — Lint & Type Check[/bold blue]\n"
            f"Directory: {BACKEND_DIR}",
            border_style="blue",
        )
    )

    results: List[CheckResult] = []

    run_all = not ruff_only and not mypy_only

    if run_all or ruff_only:
        results.append(run_ruff_check(fix))
        results.append(run_ruff_format(fix))

    if run_all or mypy_only:
        results.append(run_mypy())

    print_summary(results)

    all_passed = all(r.passed for r in results)
    if all_passed:
        console.print("\n[green bold]All checks passed.[/green bold]")
    else:
        failed = [r.name for r in results if not r.passed]
        console.print(f"\n[red bold]Failed: {', '.join(failed)}[/red bold]")
        if any("ruff" in r.name for r in results if not r.passed):
            console.print(
                "[yellow]Tip: Run with --fix to auto-fix ruff issues[/yellow]"
            )

    if ci and not all_passed:
        sys.exit(1)
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
