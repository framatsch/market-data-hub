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

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app

def test_websocket_connect():
    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/market-data") as websocket:
            websocket.send_json({"action": "subscribe", "symbols": ["AAPL"]})
            websocket.send_json({"action": "unsubscribe", "symbols": ["AAPL"]})
            websocket.close()
    except WebSocketDisconnect:
        pass
