import csv
import io
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_volatility import router
from app.dependencies import get_volatility_service
from app.main import app_error_handler
from app.utils.errors import (
    AppError,
    DataNotFoundError,
    DataValidationError,
    ProviderError,
)


@pytest.fixture
def volatility_client(volatility_env):
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(AppError, app_error_handler)
    app.dependency_overrides[get_volatility_service] = lambda: volatility_env.service
    with TestClient(app) as client:
        yield client


def test_snapshot_and_provider_shape(volatility_client):
    lseg = volatility_client.get("/volatility/aapl").json()["data"]
    ibkr = volatility_client.get("/volatility/aapl?provider=IBKR").json()["data"]
    assert lseg.keys() == ibkr.keys()
    assert lseg["symbol"] == "AAPL"
    for data in (lseg, ibkr):
        assert [item["tenor_days"] for item in data["implied"]] == [30, 60, 90]
        assert data["implied"][0]["iv"] == "0.2677"
    assert lseg["method"] == "provider_atm_index"
    assert ibkr["method"] == "provider_model_30d"


def test_history_defaults_and_explicit_tenor(volatility_client, volatility_env):
    response = volatility_client.get("/volatility/AAPL/history?tenor_days=30")
    assert response.status_code == 200
    args = volatility_env.lseg.get_implied_volatility_history.call_args.args
    assert args[1:3] == (date.today() - timedelta(days=365), date.today())
    assert len(response.json()["data"]["points"]) == 25


@pytest.mark.parametrize("suffix", ["", "/history", "/stats"])
def test_csv_export(volatility_client, suffix):
    response = volatility_client.get(f"/volatility/AAPL{suffix}?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=AAPL_volatility" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["symbol"] == "AAPL"
    if suffix == "":
        assert len(rows) == 3 and rows[0]["iv"] == "0.2677"
    elif suffix == "/history":
        assert len(rows) == 25 and rows[0]["iv"] == "0.2000"
    else:
        assert rows[0]["current"] == "0.2000" and rows[0]["iv_percentile"] == "0.00"


@pytest.mark.parametrize("query", [
    "/history?tenor_days=45", "/history?start=2026-11-05&end=2026-01-01",
    "?sec_type=option", "?format=invalid", "/stats?window=5", "/stats?window=757",
])
def test_invalid_requests(volatility_client, query):
    assert volatility_client.get(f"/volatility/AAPL{query}").status_code == 422


def test_stats_response(volatility_client):
    response = volatility_client.get("/volatility/AAPL/stats")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["window"] == 252 and data["window_points"] == 25
    assert data["iv_rank"] is None and data["iv_percentile"] == "0.00"


@pytest.mark.parametrize("query", ["/history?sec_type=future", "/history?tenor_days=60", "/stats?sec_type=future"])
def test_unsupported_ibkr_combination(volatility_client, volatility_env, query):
    response = volatility_client.get(f"/volatility/ES{query}&provider=ibkr")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"
    volatility_env.ibkr.get_implied_volatility_history.assert_not_awaited()


def test_no_default_and_wrong_capability(volatility_client, volatility_env):
    response = volatility_client.get("/volatility/AAPL?provider=schwab")
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_PROVIDER"
    volatility_env.registry.default_volatility_provider = None
    assert volatility_client.get("/volatility/AAPL").status_code == 503


@pytest.mark.parametrize("error,status", [
    (DataNotFoundError("ImpliedVolatility", "AAPL", {"reason": "no_iv_data"}), 404),
    (ProviderError("Not entitled", code="PROVIDER_NOT_AVAILABLE"), 503),
    (DataValidationError("Market mismatch", {"expected_market": ["COMFUT"], "market": "OPRA"}), 422),
])
def test_provider_error_mapping(volatility_client, volatility_env, error, status):
    volatility_env.lseg.get_implied_volatility.side_effect = error
    response = volatility_client.get("/volatility/AAPL")
    assert response.status_code == status
    assert response.json()["error"]["code"] == error.code


def test_ibkr_ric_rejected(volatility_client, volatility_env):
    volatility_env.ibkr.get_implied_volatility.side_effect = DataValidationError("ric is LSEG-only")
    assert volatility_client.get("/volatility/AAPL?provider=ibkr&ric=AAPLATMIV.U").status_code == 422
