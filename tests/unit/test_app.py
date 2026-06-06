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
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "OK"

def test_list_providers(client):
    response = client.get("/providers")
    assert response.status_code == 200
    assert "data" in response.json()
    assert "available" in response.json()["data"]

def test_404_handling(client):
    response = client.get("/non-existent-path")
    assert response.status_code == 404


def test_admin_route_registered(client):
    response = client.get("/admin")
    # Accept 200 when UI bundle exists, or explicit 404 payload when not built
    assert response.status_code in (200, 404)
    if response.status_code == 404:
        assert response.json()["detail"] == "Admin UI not built"
