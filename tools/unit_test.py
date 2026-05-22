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
"""Unit and integration test runner for the tradesensei backend.

Runs pytest via uv against the backend test suite with proper
coverage reporting.

Usage:
    python tools/unit_test.py                # Run all tests
    python tools/unit_test.py --unit         # Unit tests only (no DB)
    python tools/unit_test.py --integration  # Integration tests only (requires DB)
    python tools/unit_test.py --coverage     # Full run + HTML coverage report
    python tools/unit_test.py --ci           # Exit 1 on failure + XML coverage (for CI)
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
BACKEND_DIR = ROOT_DIR / "backend"


def run_pytest(args: List[str], env_overrides: dict | None = None) -> int:
    """Run pytest via uv run in the backend directory."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    cmd = ["uv", "run", "pytest"] + args
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]\n")

    result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)
    return result.returncode


@click.command()
@click.option("--unit", is_flag=True, help="Run unit tests only (tests/unit/)")
@click.option(
    "--integration",
    is_flag=True,
    help="Run integration tests only (tests/integration/)",
)
@click.option("--coverage", is_flag=True, help="Generate HTML coverage report")
@click.option(
    "--ci", is_flag=True, help="CI mode: XML coverage output, exit 1 on failure"
)
def main(unit: bool, integration: bool, coverage: bool, ci: bool) -> None:
    """Run the tradesensei backend test suite."""
    if not BACKEND_DIR.exists():
        console.print(f"[red]Backend directory not found: {BACKEND_DIR}[/red]")
        sys.exit(1)

    console.print(
        Panel.fit(
            "[bold magenta]Trade Sensei — Test Runner[/bold magenta]\n"
            f"Backend: {BACKEND_DIR}",
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
            "[bold]Scope:[/bold] integration tests only (requires running DB)"
        )
    else:
        pytest_args += ["tests/"]
        console.print("[bold]Scope:[/bold] all tests")

    # Coverage
    pytest_args += ["--cov=app", "--cov-fail-under=74"]
    if ci:
        pytest_args += ["--cov-report=xml:coverage.xml", "--cov-report=term-missing"]
        console.print("[bold]Mode:[/bold] CI (XML coverage output)")
    elif coverage:
        pytest_args += ["--cov-report=html:htmlcov", "--cov-report=term-missing"]
        console.print(
            "[bold]Mode:[/bold] HTML coverage report → backend/htmlcov/index.html"
        )
    else:
        pytest_args += ["--cov-report=term-missing"]

    exit_code = run_pytest(pytest_args)

    if exit_code == 0:
        console.print("\n[green bold]All tests passed.[/green bold]")
    else:
        console.print("\n[red bold]Tests failed.[/red bold]")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
