#!/usr/bin/env python3
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

"""Schwab CLI — download accounts, positions, and transactions from the
Charles Schwab Trader API into the wrapped JSON format consumed by the
Trade Sensei importer.

Subcommands:
  accounts      List all linked Schwab accounts.
  positions     Fetch positions snapshot only (diagnostic output).
  transactions  Fetch TRADE transactions and write a wrapped JSON file.
  quotes        Save raw market quotes and inspect volatility-related fields.
  refresh       Force a full OAuth re-authentication and refresh all tokens.

Open positions are surfaced by the importer from the downloaded
*transactions*, not from the positions[] snapshot: an opening trade with no
matching later close is left as an open lot. Make sure the fetched window
(--start on `transactions`) includes each open position's opening trade.

Requires env vars SCHWAB_APP_KEY, SCHWAB_APP_SECRET, and optionally
SCHWAB_CALLBACK_URL (default https://127.0.0.1). These are read from the
environment or a `.env` file next to this script (or in the project root).

Token encryption is required. Set SCHWAB_TOKEN_ENCRYPTION_KEY (preferred)
or BROKER_ENCRYPTION_KEY.

Quote diagnostics (no account access, no IV calculation or unit conversion):
  python schwab_cli.py quotes
  python schwab_cli.py quotes '$SPX' SPY AAPL --output schwab_quotes.json --raw
Quote symbols containing '$' must be single-quoted to prevent shell expansion.
"""

import argparse
import json
import logging
import os
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[assignment]

if load_dotenv is not None:
    # Look for a .env in the current working directory, then next to the tool, then in the project root.
    _here = Path(__file__).resolve().parent
    for _candidate in (Path.cwd() / ".env", _here / ".env", _here.parent / ".env"):
        if _candidate.exists():
            load_dotenv(_candidate)
            break

try:
    import schwabdev
    from requests.exceptions import RequestException
    from schwabdev.tokens import Tokens
except ImportError:
    sys.exit("schwabdev not installed. Run: pip install schwabdev")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
except ImportError:
    sys.exit("rich not installed. Run: pip install rich")

console = Console()

# schwabdev bug: _set_tokens receives False on failed token exchange but calls
# .get() on it without checking. Guard against a non-dict token_dictionary.
_orig_set_tokens = Tokens._set_tokens


def _safe_set_tokens(self, at_issued, rt_issued, token_dictionary):  # type: ignore[no-untyped-def]
    if not isinstance(token_dictionary, dict):
        return False
    return _orig_set_tokens(self, at_issued, rt_issued, token_dictionary)


Tokens._set_tokens = _safe_set_tokens  # type: ignore[method-assign]


DEFAULT_OUTPUT_FILE = Path.cwd() / "transactions.json"
DEFAULT_POSITIONS_FILE = Path.cwd() / "positions.json"
DEFAULT_QUOTES_FILE = Path.cwd() / "schwab_quotes.json"
DEFAULT_DAYS_BACK = 90


def _auth(auth_url: str) -> str:
    """Prompt for OAuth callback URL. Fixes missing redirect_uri encoding in schwabdev."""
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1").rstrip("/")

    parsed = urllib.parse.urlparse(auth_url)
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    params["redirect_uri"] = [urllib.parse.quote(callback_url, safe="")]
    auth_url = urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode({k: v[0] for k, v in params.items()}))
    )

    console.print(
        Panel(
            f"[bold cyan]Open this URL in your browser:[/bold cyan]\n\n{auth_url}\n\n"
            f"[yellow]After clicking Allow, your browser redirects to {callback_url}?code=...[/yellow]\n"
            f"[yellow]The page will NOT load — that is expected.[/yellow]\n"
            f"[bold red]Copy the full URL from the address bar IMMEDIATELY (do NOT wait for ERR_TIMED_OUT)[/bold red]",
            title="[bold]Schwab OAuth",
            border_style="cyan",
        )
    )
    return console.input("[bold green]Paste the full redirect URL here:[/bold green] ").strip()


def _make_client() -> schwabdev.Client:
    """Create and return an authenticated Schwab client."""
    app_key = os.environ.get("SCHWAB_APP_KEY")
    app_secret = os.environ.get("SCHWAB_APP_SECRET")
    callback_url = os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1").rstrip("/")

    if not app_key or not app_secret:
        sys.exit("ERROR: SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in .env or the environment.")

    encryption_key = os.environ.get("SCHWAB_TOKEN_ENCRYPTION_KEY") or os.environ.get("BROKER_ENCRYPTION_KEY")
    if not encryption_key:
        sys.exit(
            "ERROR: Missing token encryption key. Set SCHWAB_TOKEN_ENCRYPTION_KEY "
            "(preferred) or BROKER_ENCRYPTION_KEY before using this tool."
        )

    return schwabdev.Client(
        app_key=app_key,
        app_secret=app_secret,
        callback_url=callback_url,
        encryption=encryption_key,
        call_on_auth=_auth,
        open_browser_for_auth=False,
    )


def _fetch_linked_accounts(client: schwabdev.Client) -> list:
    resp = client.linked_accounts()
    if not resp.ok:
        sys.exit(f"ERROR fetching accounts: {resp.status_code} {resp.text}")
    return resp.json()


def _match_account(accounts: list, account_filter: str | None) -> list:
    """Return the subset of accounts to process, or exit with a helpful message."""
    if not accounts:
        sys.exit("No linked accounts found.")

    if account_filter is None:
        if len(accounts) == 1:
            return accounts
        numbers = [a.get("accountNumber", "?") for a in accounts]
        console.print(
            Panel(
                "[yellow]Multiple accounts found — please specify one with [bold]--account[/bold]:[/yellow]\n"
                + "\n".join(f"  • {n}" for n in numbers),
                title="[bold red]Account required",
                border_style="red",
            )
        )
        sys.exit(1)

    matched = [a for a in accounts if str(a.get("accountNumber", "")) == str(account_filter)]
    if not matched:
        numbers = [a.get("accountNumber", "?") for a in accounts]
        console.print(
            Panel(
                f"[red]Account [bold]{account_filter}[/bold] not found.[/red]\n"
                "Available accounts:\n" + "\n".join(f"  • {n}" for n in numbers),
                title="[bold red]Account not found",
                border_style="red",
            )
        )
        sys.exit(1)

    return matched


def _token_status_panel(tokens) -> Panel:
    """Build a rich Panel showing current token expiry times."""
    import datetime as _dt

    now = _dt.datetime.now(_dt.UTC)

    at_expires = tokens._access_token_issued + _dt.timedelta(seconds=tokens._access_token_timeout)
    rt_expires = tokens._refresh_token_issued + _dt.timedelta(seconds=tokens._refresh_token_timeout)

    at_remaining = at_expires - now
    rt_remaining = rt_expires - now

    def _fmt(td: _dt.timedelta) -> str:
        if td.total_seconds() < 0:
            return "[bold red]EXPIRED[/bold red]"
        total = int(td.total_seconds())
        d, rem = divmod(total, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        parts.append(f"{m}m")
        color = "green" if td.total_seconds() > 3600 else "yellow"
        return f"[{color}]{' '.join(parts)}[/{color}]"

    lines = [
        f"[bold]Access token:[/bold]  issued {tokens._access_token_issued.strftime('%Y-%m-%d %H:%M')} UTC  •  expires in {_fmt(at_remaining)}",
        f"[bold]Refresh token:[/bold] issued {tokens._refresh_token_issued.strftime('%Y-%m-%d %H:%M')} UTC  •  expires in {_fmt(rt_remaining)}",
    ]
    return Panel("\n".join(lines), title="[bold cyan]Token Status", border_style="cyan")


def cmd_refresh(_args) -> None:
    """Force a full OAuth re-authentication and persist new tokens."""
    client = _make_client()

    console.print(_token_status_panel(client.tokens))
    console.print("[yellow]Forcing refresh token renewal — browser auth required…[/yellow]")

    client.update_tokens(force_refresh_token=True)

    console.print("\n[green]✓ Tokens refreshed.[/green]")
    console.print(_token_status_panel(client.tokens))


def cmd_accounts(_args) -> None:
    """List all linked accounts and exit."""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Connecting to Schwab...", total=None)
        client = _make_client()
        progress.update(task, description="Fetching linked accounts...")
        accounts = _fetch_linked_accounts(client)

    table = Table(title="Linked Accounts", show_header=True, header_style="bold cyan")
    table.add_column("Account Number", style="bold")
    table.add_column("Hash", style="dim")

    for a in accounts:
        table.add_row(
            a.get("accountNumber", "?"),
            a.get("hashValue", "?"),
        )

    console.print(table)


def cmd_positions(args) -> None:
    """Fetch positions for one or all accounts and save to JSON."""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Connecting to Schwab...", total=None)
        client = _make_client()

        progress.update(task, description="Fetching linked accounts...")
        all_linked = _fetch_linked_accounts(client)
        target_accounts = _match_account(all_linked, args.account)

        all_accounts = []
        for account in target_accounts:
            account_hash = account.get("hashValue")
            account_number = account.get("accountNumber", "unknown")

            progress.update(task, description=f"Fetching positions for account {account_number}...")
            resp = client.account_details(accountHash=account_hash, fields="positions")
            if not resp.ok:
                console.print(f"[yellow]WARNING account {account_number}: {resp.status_code} {resp.text}[/yellow]")
                positions = []
            else:
                data = resp.json()
                positions = data.get("securitiesAccount", {}).get("positions", [])

            all_accounts.append(
                {
                    "accountNumber": account_number,
                    "accountHash": account_hash,
                    "positions": positions,
                }
            )

        progress.update(task, description="Saving output...")

        output = {
            "fetchedAt": datetime.now(UTC).isoformat(),
            "accounts": all_accounts,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2))

    table = Table(title="Positions", show_header=True, header_style="bold cyan")
    table.add_column("Account", style="bold")
    table.add_column("Positions", justify="right")

    for a in all_accounts:
        table.add_row(a["accountNumber"], str(len(a["positions"])))

    total = sum(len(a["positions"]) for a in all_accounts)
    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")

    console.print(table)
    console.print(f"\n[green]✓ Saved → [bold]{args.output}[/bold][/green]")


def cmd_transactions(args) -> None:
    """Fetch transactions for one or all accounts and save to JSON."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=DEFAULT_DAYS_BACK)

    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d")

    start_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    console.print(
        Panel(
            f"[bold]Date range:[/bold] {start_date.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}\n"
            f"[bold]Output:[/bold] {args.output}",
            title="[bold cyan]Schwab Transaction Fetcher",
            border_style="cyan",
        )
    )

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Connecting to Schwab...", total=None)
        client = _make_client()

        progress.update(task, description="Fetching linked accounts...")
        all_linked = _fetch_linked_accounts(client)
        target_accounts = _match_account(all_linked, args.account)

        all_accounts = []
        for account in target_accounts:
            account_hash = account.get("hashValue")
            account_number = account.get("accountNumber", "unknown")

            progress.update(task, description=f"Fetching transactions for account {account_number}...")
            resp = client.transactions(
                accountHash=account_hash,
                startDate=start_str,
                endDate=end_str,
                types="TRADE",
            )
            transactions = []
            if resp.ok:
                transactions = resp.json()
            else:
                console.print(f"[yellow]WARNING account {account_number}: {resp.status_code} {resp.text}[/yellow]")

            all_accounts.append(
                {
                    "accountNumber": account_number,
                    "accountHash": account_hash,
                    "transactions": transactions,
                }
            )

        progress.update(task, description="Saving output...")

        output = {
            "fetchedAt": datetime.now(UTC).isoformat(),
            "dateRange": {"start": start_str, "end": end_str},
            "accounts": all_accounts,
        }

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2))

    table = Table(title="Fetched Transactions", show_header=True, header_style="bold cyan")
    table.add_column("Account", style="bold")
    table.add_column("Transactions", justify="right")

    for a in all_accounts:
        table.add_row(a["accountNumber"], str(len(a["transactions"])))

    total = sum(len(a["transactions"]) for a in all_accounts)
    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")

    console.print(table)
    console.print(f"\n[green]✓ Saved → [bold]{args.output}[/bold][/green]")


def _volatility_fields(data: Any, path: str = "$") -> list[tuple[str, Any]]:
    """Find raw candidate fields without claiming they represent underlying IV."""
    found = []
    if isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}"
            if "volatil" in key.lower() or key.lower() in {
                "impliedyield", "impliedvol", "iv", "hv",
            }:
                found.append((child_path, value))
            found.extend(_volatility_fields(value, child_path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            found.extend(_volatility_fields(value, f"{path}[{index}]"))
    return found


def cmd_quotes(args) -> None:
    """Inspect the complete /quotes response, bypassing MDH's field mapping."""
    symbols = list(dict.fromkeys(symbol.strip().upper() for symbol in args.symbols if symbol.strip()))
    if not symbols:
        sys.exit("ERROR: Provide at least one non-empty symbol (quote '$SPX' in your shell).")

    client = _make_client()
    try:
        # Explicitly request all sections, including quote and fundamental.
        resp = client.quotes(symbols=",".join(symbols), fields="all")
    except RequestException:
        sys.exit("ERROR: Schwab quote request failed (network/timeout).")
    if not resp.ok:
        sys.exit(f"ERROR fetching quotes: HTTP {resp.status_code}. Check authentication and market-data permissions.")
    try:
        data = resp.json()
    except ValueError:
        sys.exit("ERROR: Schwab returned a non-JSON quote response.")
    if not isinstance(data, dict):
        sys.exit("ERROR: Expected a JSON object from Schwab /quotes.")

    # Preserve the full market-data payload: no wrapping, filtering or conversion.
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    except OSError:
        sys.exit("ERROR: Could not write quote output file.")

    table = Table(title="Schwab /quotes — raw volatility candidates", header_style="bold cyan")
    table.add_column("Symbol")
    table.add_column("Asset type")
    table.add_column("JSON path")
    table.add_column("Raw value")
    missing = []
    for symbol in symbols:
        entry = data.get(symbol)
        if not isinstance(entry, dict) or not entry:
            missing.append(symbol)
            table.add_row(symbol, "—", "Quote missing; inspect saved JSON", "—")
            continue
        asset_type = str(entry.get("assetMainType", "unknown"))
        fields = _volatility_fields(entry)
        if fields:
            for path, value in fields:
                table.add_row(symbol, asset_type, path, json.dumps(value, ensure_ascii=False))
        else:
            table.add_row(symbol, asset_type, "No volatility-related fields", "—")

    console.print(table)
    console.print(
        "Raw values only: volatility is NOT yet verified as underlying IV; "
        "impliedYield is a separate yield field, NOT IV. No unit conversion applied.",
        markup=False,
    )
    console.print(f"Full market-data JSON saved to {args.output}", markup=False)
    if args.raw:
        console.print(payload, markup=False, highlight=False, soft_wrap=True)
    if missing:
        sys.exit(f"ERROR: Missing quotes for {', '.join(missing)}; inspect the saved JSON for provider errors.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Schwab CLI — fetch accounts, positions, transactions, and raw market quotes.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "refresh",
        help="Force a full OAuth re-authentication and refresh all tokens.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    subparsers.add_parser(
        "accounts",
        help="List all linked accounts and exit.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    pos = subparsers.add_parser(
        "positions",
        help="Fetch current positions snapshot only (diagnostics; not import-ready).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    pos.add_argument("--account", "-a", help="Account number to fetch (required when multiple accounts exist)")
    pos.add_argument("--output", "-o", type=Path, default=DEFAULT_POSITIONS_FILE, help="Output JSON file path")

    tx = subparsers.add_parser(
        "transactions",
        help="Fetch TRADE transactions and save to JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    tx.add_argument("--account", "-a", help="Account number to fetch (required when multiple accounts exist)")
    tx.add_argument("--start", help="Start date (YYYY-MM-DD)")
    tx.add_argument("--end", help="End date (YYYY-MM-DD)")
    tx.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT_FILE, help="Output JSON file path")

    quotes = subparsers.add_parser(
        "quotes",
        help="Save raw /quotes JSON and inspect volatility fields (no IV calculation).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    quotes.add_argument("symbols", nargs="*", default=["$SPX", "SPY", "AAPL"], help="Space-separated symbols; single-quote '$SPX'")
    quotes.add_argument("--output", "-o", type=Path, default=DEFAULT_QUOTES_FILE, help="Full raw market-data JSON file path")
    quotes.add_argument("--raw", action="store_true", help="Also print the complete JSON response")

    args = parser.parse_args()

    if args.command == "refresh":
        cmd_refresh(args)
    elif args.command == "accounts":
        cmd_accounts(args)
    elif args.command == "positions":
        cmd_positions(args)
    elif args.command == "transactions":
        cmd_transactions(args)
    elif args.command == "quotes":
        cmd_quotes(args)


if __name__ == "__main__":
    main()
