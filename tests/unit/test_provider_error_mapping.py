"""Provider failures map to specific errors instead of generic 500s."""

import httpx
import pytest

from app.providers.financialdatasets import FinancialDatasetsProvider
from app.providers.polygon import _wrap_error
from app.utils.errors import DataNotFoundError, ProviderError, ProviderTimeoutError


def _status_error(url: str, status: int, body: str = "") -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request, text=body)
    )


def test_polygon_rate_limit_is_not_an_internal_error():
    exc = _status_error("https://api.polygon.io/v2/x?apiKey=SECRET123", 429)
    mapped = _wrap_error("Polygon API error", exc, "XLK")
    assert isinstance(mapped, ProviderTimeoutError)
    assert "SECRET123" not in mapped.message


def test_polygon_generic_error_redacts_api_key():
    exc = RuntimeError("failed for https://api.polygon.io/x?apiKey=SECRET123&adjusted=true")
    mapped = _wrap_error("Polygon API error", exc, "XLK")
    assert type(mapped) is ProviderError
    assert "SECRET123" not in mapped.message
    assert "apiKey=***" in mapped.message


def test_polygon_wrap_keeps_existing_app_errors():
    original = DataNotFoundError("Ticker", "XLK")
    assert _wrap_error("ctx", original, "XLK") is original


@pytest.mark.parametrize("status,expect_not_found", [(400, True), (500, False)])
def test_financialdatasets_invalid_ticker_is_not_found(status, expect_not_found):
    provider = FinancialDatasetsProvider.__new__(FinancialDatasetsProvider)
    body = '{"error":"Invalid ticker"}' if expect_not_found else "oops"
    mapped = provider._http_error(
        _status_error("https://api.financialdatasets.ai/x", status, body), "SPX"
    )
    assert isinstance(mapped, DataNotFoundError) is expect_not_found
