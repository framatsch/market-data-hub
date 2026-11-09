from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes_ws


def _client():
    app = FastAPI()
    app.include_router(routes_ws.router)
    return TestClient(app)


def test_subscription_echoes_canonical_symbol_for_future_alias():
    with _client().websocket_connect("/ws/prices") as ws:
        ws.send_json({"type": "subscribe", "symbols": ["/es", "aapl"]})
        assert ws.receive_json()["symbol"] == "F:ES"


def test_subscription_accepts_index_alias():
    with _client().websocket_connect("/ws/prices") as ws:
        ws.send_json({"type": "subscribe", "symbols": ["^spx"]})
        assert ws.receive_json()["symbol"] == "I:SPX"


def test_invalid_symbol_is_reported_and_connection_stays_open():
    with _client().websocket_connect("/ws/prices") as ws:
        ws.send_json({"type": "subscribe", "symbols": ["O:AAPL250117C00150000"]})
        error = ws.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "DATA_VALIDATION_ERROR"
        ws.send_json({"type": "subscribe", "symbols": [".SPX"]})
        assert ws.receive_json()["details"]["suggestion"] == "I:SPX"
