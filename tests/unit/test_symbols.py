import pytest

from app.utils.errors import DataValidationError
from app.utils.symbols import (
    COMPANY_TYPES,
    OPTION_UNDERLYING_TYPES,
    PRICE_TYPES,
    STREAM_TYPES,
    VOLATILITY_TYPES,
    ParsedSymbol,
    normalize_sec_type,
    parse_symbol,
    strip_option_prefix,
)


@pytest.mark.parametrize(
    "raw,root,sec_type,canonical",
    [
        ("f:es", "ES", "future", "F:ES"),
        ("I:SPX", "SPX", "index", "I:SPX"),
        ("^spx", "SPX", "index", "I:SPX"),
        ("/ES", "ES", "future", "F:ES"),
        (" aapl ", "AAPL", "stock", "AAPL"),
        ("O:AAPL250117C00150000", "AAPL250117C00150000", "option", "O:AAPL250117C00150000"),
        ("BRK.B", "BRK.B", "stock", "BRK.B"),
        ("BRK_B", "BRK_B", "stock", "BRK_B"),
        (" i : spx ", "SPX", "index", "I:SPX"),
    ],
)
def test_grammar(raw, root, sec_type, canonical):
    parsed = parse_symbol(raw)
    assert (parsed.root, parsed.sec_type, parsed.canonical) == (
        root,
        sec_type,
        canonical,
    )
    assert str(parsed) == canonical


def test_unknown_prefix_lists_supported_prefixes():
    with pytest.raises(DataValidationError) as exc:
        parse_symbol("X:BTCUSD")
    assert exc.value.code == "DATA_VALIDATION_ERROR"
    assert exc.value.details["supported_prefixes"] == ["F", "I", "O"]


@pytest.mark.parametrize("raw", ["", "  ", "F:", "^", "/", "I: ", "F:ES:Z6", "I:A:B"])
def test_empty_or_malformed_root(raw):
    with pytest.raises(DataValidationError):
        parse_symbol(raw)


@pytest.mark.parametrize("raw,suggestion", [(".SPX", "I:SPX"), ("$spx", "I:SPX")])
def test_provider_native_notation_rejected(raw, suggestion):
    with pytest.raises(DataValidationError) as exc:
        parse_symbol(raw)
    assert exc.value.details["suggestion"] == suggestion


def test_native_marker_after_prefix_rejected():
    with pytest.raises(DataValidationError) as exc:
        parse_symbol("I:.SPX")
    assert exc.value.details["suggestion"] == "I:SPX"


@pytest.mark.parametrize(
    "value,expected",
    [("INDEX", "index"), ("Stock", "stock"), ("STK", "stock"), ("etf", "etf")],
)
def test_sec_type_vocabulary(value, expected):
    assert normalize_sec_type(value) == expected


def test_sec_type_none_and_blank():
    assert normalize_sec_type(None) is None
    assert normalize_sec_type("  ") is None


def test_invalid_sec_type():
    with pytest.raises(DataValidationError) as exc:
        parse_symbol("AAPL", "bond")
    assert "index" in exc.value.details["supported"]


@pytest.mark.parametrize(
    "raw,sec_type,canonical",
    [
        ("ES", "future", "F:ES"),
        ("ES", "FUTURE", "F:ES"),
        ("SPX", "INDEX", "I:SPX"),
        ("AAPL", "STK", "AAPL"),
        ("SPY", "etf", "SPY"),
        ("F:ES", "future", "F:ES"),
        ("^SPX", "index", "I:SPX"),
        ("/ES", "future", "F:ES"),
    ],
)
def test_sec_type_resolution(raw, sec_type, canonical):
    assert parse_symbol(raw, sec_type).canonical == canonical


def test_etf_keeps_sec_type_without_prefix():
    parsed = parse_symbol("SPY", "etf")
    assert parsed == ParsedSymbol("SPY", "etf")
    assert parsed.canonical == "SPY"


@pytest.mark.parametrize(
    "raw,sec_type",
    [("F:ES", "stock"), ("I:SPX", "future"), ("^SPX", "future"), ("F:ES", "etf")],
)
def test_prefix_and_sec_type_conflict(raw, sec_type):
    with pytest.raises(DataValidationError) as exc:
        parse_symbol(raw, sec_type)
    assert exc.value.details["sec_type"] == sec_type


def test_equity_ticker_equal_to_futures_root_stays_stock():
    assert parse_symbol("CL").sec_type == "stock"


def test_allowed_enforced_with_details():
    with pytest.raises(DataValidationError) as exc:
        parse_symbol("F:ES", allowed=COMPANY_TYPES)
    assert exc.value.details["sec_type"] == "future"
    assert exc.value.details["supported"] == ["etf", "stock"]


def test_endpoint_type_sets():
    assert PRICE_TYPES == {"stock", "etf", "index", "future"}
    assert VOLATILITY_TYPES == PRICE_TYPES
    assert STREAM_TYPES == PRICE_TYPES
    assert OPTION_UNDERLYING_TYPES == {"stock", "etf", "index"}
    assert COMPANY_TYPES == {"stock", "etf"}
    with pytest.raises(DataValidationError):
        parse_symbol("O:AAPL250117C00150000", allowed=PRICE_TYPES)


@pytest.mark.parametrize(
    "value,expected",
    [("O:aapl250117c00150000", "AAPL250117C00150000"), ("AAPL250117C00150000", "AAPL250117C00150000")],
)
def test_strip_option_prefix(value, expected):
    assert strip_option_prefix(value) == expected


def test_strip_option_prefix_empty():
    with pytest.raises(DataValidationError):
        strip_option_prefix("O:")
