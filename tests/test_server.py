import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from backend.server import QMTServer, create_server


@pytest.fixture
def server():
    srv = QMTServer(
        account_id="test_account",
        mini_qmt_path="/tmp/mock_qmt",
        host="127.0.0.1",
        port=8001,
    )
    srv.init_trader()
    srv.setup_routes()
    return srv


@pytest.fixture
def client(server):
    return TestClient(server.app)


class TestServerHealth:
    def test_server_status(self, client):
        response = client.get("/api/server-status")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "running" in data["data"]

    def test_test_connection_without_token(self, client):
        response = client.get("/api/test-connection")
        assert response.status_code == 422


class TestServerToken:
    def test_generate_token(self, server):
        token = server.generate_token()
        assert isinstance(token, str)
        assert len(token) == 64

    def test_token_is_deterministic(self, server):
        token1 = server.generate_token()
        token2 = server.generate_token()
        assert token1 == token2

    def test_test_connection_with_valid_token(self, client, server):
        response = client.get(
            "/api/test-connection",
            headers={"X-Token": server.token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    def test_test_connection_with_invalid_token(self, client):
        response = client.get(
            "/api/test-connection",
            headers={"X-Token": "invalid-token"}
        )
        assert response.status_code == 401


class TestAccountAsset:
    def test_get_account_asset(self, client, server):
        response = client.get(
            "/api/account-asset",
            headers={"X-Token": server.token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    def test_signals_endpoint(self, client, server):
        response = client.get(
            "/api/signals",
            headers={"X-Token": server.token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)


class TestJqConversion:
    def test_jq_to_qmt_conversion(self, client, server):
        response = client.post(
            "/api/convert/jq-to-qmt",
            json={"code": "000001.XSHE"},
            headers={"X-Token": server.token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["result"] == "000001.SZ"

    def test_qmt_to_jq_conversion(self, client, server):
        response = client.post(
            "/api/convert/qmt-to-jq",
            json={"code": "000001.SZ"},
            headers={"X-Token": server.token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["result"] == "000001.XSHE"


class TestCreateServerUtil:
    def test_create_server(self):
        srv = create_server("test", "/tmp/mock", "127.0.0.1", 8002)
        assert isinstance(srv, QMTServer)
        assert srv.account_id == "test"
        assert srv.mini_qmt_path == "/tmp/mock"
