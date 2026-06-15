from datetime import datetime, timedelta, timezone
import os

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_price_service
from app.main import app
from app.providers.registry import ProviderRegistry
from app.services.price_service import PriceService


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PRIXE_INTEGRATION", "false").lower() not in {"1", "true", "yes"},
    reason="Set RUN_PRIXE_INTEGRATION=true to run Prixe integration tests",
)


@pytest.fixture
def prixe_client():
    registry = ProviderRegistry()
    service = PriceService(registry=registry)
    app.dependency_overrides[get_price_service] = lambda: service
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.integration
def test_prices_history_endpoint_with_prixe(prixe_client):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=14)

    response = prixe_client.get(
        "/prices/MSFT/history",
        params={
            "provider": "prixe",
            "interval": "1d",
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "data" in payload
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) > 0

    first_bar = payload["data"][0]
    assert first_bar["symbol"] == "MSFT"
    assert first_bar["provider"] == "prixe"
    for field in ("open", "high", "low", "close", "start", "end", "volume"):
        assert field in first_bar
