"""Offline tests for the standalone Schwab quote diagnostic command."""

import importlib.util
import io
import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("schwabdev")
pytest.importorskip("rich")
from requests.exceptions import Timeout
from rich.console import Console
from schwabdev.tokens import Tokens


@pytest.fixture(scope="module")
def cli():
    original = Tokens._set_tokens
    path = Path(__file__).resolve().parents[2] / "schwab_cli.py"
    spec = importlib.util.spec_from_file_location("schwab_cli_diagnostic", path)
    module = importlib.util.module_from_spec(spec)
    with patch("dotenv.load_dotenv"):
        spec.loader.exec_module(module)
    yield module
    Tokens._set_tokens = original


@pytest.fixture
def setup_quotes(cli, monkeypatch, tmp_path):
    stream = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=stream, width=220, color_system=None))
    client = Mock()
    monkeypatch.setattr(cli, "_make_client", lambda: client)
    args = Namespace(symbols=["$SPX", "SPY", "AAPL"], output=tmp_path / "quotes.json", raw=False)
    return client, args, stream


def test_finds_candidates_without_converting_or_dropping_null(cli):
    data = {
        "quote": {"volatility": 22.345, "impliedYield": 1.5, "totalVolume": 100},
        "fundamental": {"historicalVolatility": None},
        "other": [{"iv": 0}, {"hv": -999}],
    }
    assert cli._volatility_fields(data) == [
        ("$.quote.volatility", 22.345),
        ("$.quote.impliedYield", 1.5),
        ("$.fundamental.historicalVolatility", None),
        ("$.other[0].iv", 0),
        ("$.other[1].hv", -999),
    ]


def test_quotes_saves_complete_response_and_reports_missing_fields(cli, setup_quotes):
    client, args, stream = setup_quotes
    data = {
        "$SPX": {"assetMainType": "INDEX", "quote": {"lastPrice": 7368.19}},
        "SPY": {"assetMainType": "EQUITY", "quote": {"volatility": 22.345}},
        "AAPL": {"assetMainType": "EQUITY", "quote": {"volatility": None}, "extra": [1, 2]},
    }
    client.quotes.return_value.json.return_value = data
    args.raw = True
    cli.cmd_quotes(args)
    client.quotes.assert_called_once_with(symbols="$SPX,SPY,AAPL", fields="all")
    assert json.loads(args.output.read_text()) == data
    assert "No volatility-related fields" in stream.getvalue()
    assert "22.345" in stream.getvalue()
    assert "null" in stream.getvalue()
    assert '"extra"' in stream.getvalue()
    client.linked_accounts.assert_not_called()


def test_quotes_normalizes_and_deduplicates_symbols(cli, setup_quotes):
    client, args, _ = setup_quotes
    args.symbols = [" spy ", "SPY", ""]
    client.quotes.return_value.json.return_value = {"SPY": {"quote": {"volatility": 0}}}
    cli.cmd_quotes(args)
    client.quotes.assert_called_once_with(symbols="SPY", fields="all")


def test_missing_symbol_saves_provider_error_before_failing(cli, setup_quotes):
    client, args, _ = setup_quotes
    data = {"errors": {"invalidSymbols": ["$SPX", "SPY", "AAPL"]}}
    client.quotes.return_value.json.return_value = data
    with pytest.raises(SystemExit, match="Missing quotes"):
        cli.cmd_quotes(args)
    assert json.loads(args.output.read_text()) == data


def test_http_error_does_not_save_or_print_response_body(cli, setup_quotes):
    client, args, stream = setup_quotes
    client.quotes.return_value.ok = False
    client.quotes.return_value.status_code = 403
    client.quotes.return_value.text = "sensitive error body"
    with pytest.raises(SystemExit, match="HTTP 403"):
        cli.cmd_quotes(args)
    assert not args.output.exists()
    assert "sensitive" not in stream.getvalue()


@pytest.mark.parametrize("bad_json", [None, []])
def test_non_object_response_fails_without_saving(cli, setup_quotes, bad_json):
    client, args, _ = setup_quotes
    client.quotes.return_value.json.return_value = bad_json
    with pytest.raises(SystemExit, match="Expected a JSON object"):
        cli.cmd_quotes(args)
    assert not args.output.exists()


def test_non_json_response_fails(cli, setup_quotes):
    client, args, _ = setup_quotes
    client.quotes.return_value.json.side_effect = ValueError()
    with pytest.raises(SystemExit, match="non-JSON"):
        cli.cmd_quotes(args)


def test_network_timeout_fails_without_saving(cli, setup_quotes):
    client, args, _ = setup_quotes
    client.quotes.side_effect = Timeout()
    with pytest.raises(SystemExit, match="network/timeout"):
        cli.cmd_quotes(args)
    assert not args.output.exists()


def test_empty_symbols_do_not_authenticate(cli, monkeypatch, tmp_path):
    make_client = Mock()
    monkeypatch.setattr(cli, "_make_client", make_client)
    with pytest.raises(SystemExit, match="non-empty symbol"):
        cli.cmd_quotes(Namespace(symbols=[" "], output=tmp_path / "quotes.json", raw=False))
    make_client.assert_not_called()


def test_cli_default_symbols(cli, monkeypatch):
    command = Mock()
    monkeypatch.setattr(cli, "cmd_quotes", command)
    monkeypatch.setattr(sys, "argv", ["schwab_cli.py", "quotes"])
    cli.main()
    assert command.call_args.args[0].symbols == ["$SPX", "SPY", "AAPL"]


def test_cli_explicit_symbols_and_output(cli, monkeypatch, tmp_path):
    command = Mock()
    output = tmp_path / "raw.json"
    monkeypatch.setattr(cli, "cmd_quotes", command)
    monkeypatch.setattr(sys, "argv", ["schwab_cli.py", "quotes", "$SPX", "--output", str(output), "--raw"])
    cli.main()
    args = command.call_args.args[0]
    assert args.symbols == ["$SPX"]
    assert args.output == output
    assert args.raw is True
