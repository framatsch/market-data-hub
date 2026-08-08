#!/usr/bin/env python3
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

"""Unit and integration test runner for the market-data-hub.

Runs pytest via uv against the test suite with proper
coverage reporting.

Usage:
    python tools/unit_test.py                # Run all tests
    python tools/unit_test.py --unit         # Unit tests only
    python tools/unit_test.py --integration  # Integration tests only
    python tools/unit_test.py --output html  # Full run + HTML coverage report
    python tools/unit_test.py --output xml   # XML coverage output
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.panel import Panel

console = Console()

ROOT_DIR = Path(__file__).parent.parent


def run_pytest(args: List[str], env_overrides: dict | None = None) -> int:
    """Run pytest via uv run in the root directory."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    cmd = ["uv", "run", "pytest"] + args
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]\n")

    result = subprocess.run(cmd, cwd=ROOT_DIR, env=env)
    return result.returncode


@click.command()
@click.option("--unit", is_flag=True, help="Run unit tests only (tests/unit/)")
@click.option(
    "--integration",
    is_flag=True,
    help="Run integration tests only (tests/integration/)",
)
@click.option(
    "--output",
    type=str,
    default="",
    help="Comma-separated coverage report formats (e.g. xml,html). 'term-missing' is always included.",
)
def main(unit: bool, integration: bool, output: str) -> None:
    """Run the market-data-hub test suite."""
    if not ROOT_DIR.exists():
        console.print(f"[red]Root directory not found: {ROOT_DIR}[/red]")
        sys.exit(1)

    console.print(
        Panel.fit(
            "[bold magenta]Market Data Hub — Test Runner[/bold magenta]\n"
            f"Project Root: {ROOT_DIR}",
            border_style="magenta",
        )
    )

    pytest_args: List[str] = ["-v"]

    # Scope
    if unit and not integration:
        pytest_args += ["tests/unit/"]
        console.print("[bold]Scope:[/bold] unit tests only")
    elif integration and not unit:
        pytest_args += ["tests/integration/"]
        console.print(
            "[bold]Scope:[/bold] integration tests only (requires running DB/Provider)"
        )
    else:
        pytest_args += ["tests/"]
        console.print("[bold]Scope:[/bold] all tests")

    # Coverage
    pytest_args += ["--cov=app", "--cov-fail-under=70", "--cov-report=term-missing"]
    
    outputs = [o.strip() for o in output.split(",")] if output else []
    
    if "xml" in outputs:
        pytest_args += ["--cov-report=xml:coverage.xml"]
        console.print("[bold]Mode:[/bold] XML coverage output → coverage.xml")
        
    if "html" in outputs:
        pytest_args += ["--cov-report=html:htmlcov"]
        console.print(
            "[bold]Mode:[/bold] HTML coverage report → htmlcov/index.html"
        )

    exit_code = run_pytest(pytest_args)

    if exit_code == 0:
        console.print("\n[green bold]All tests passed.[/green bold]")
    else:
        console.print("\n[red bold]Tests failed.[/red bold]")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
