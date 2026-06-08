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
        host="0.0.0.0",
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

    def test_generate_token_unique(self, server):
        token1 = server.generate_token()
        token2 = server.generate_token()
        assert token1 != token2
        assert len(token1) == 64
        assert len(token2) == 64

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
        srv = create_server("test", "/tmp/mock", "0.0.0.0", 8002)
        assert isinstance(srv, QMTServer)
        assert srv.account_id == "test"
        assert srv.mini_qmt_path == "/tmp/mock"


class TestStrategyManagement:
    """策略管理 CRUD API 测试"""

    def test_list_strategies_empty(self, client, server):
        response = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)

    def test_create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "测试策略", "description": "描述", "allocated_funds": 50000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["name"] == "测试策略"
        assert data["data"]["allocated_funds"] == 50000
        assert "token" in data["data"]
        assert "id" in data["data"]

    def test_create_and_list(self, client, server):
        client.post(
            "/api/strategies",
            json={"name": "策略A"},
            headers={"X-Token": server.token},
        )
        response = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        data = response.json()
        assert len(data["data"]) >= 1

    def test_update_strategy(self, client, server):
        create_resp = client.post(
            "/api/strategies",
            json={"name": "原始名称"},
            headers={"X-Token": server.token},
        )
        sid = create_resp.json()["data"]["id"]

        response = client.put(
            f"/api/strategies/{sid}",
            json={"name": "新名称", "enabled": False},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["name"] == "新名称"
        assert data["data"]["enabled"] is False

    def test_update_nonexistent(self, client, server):
        response = client.put(
            "/api/strategies/nonexistent",
            json={"name": "X"},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 404

    def test_delete_strategy(self, client, server):
        create_resp = client.post(
            "/api/strategies",
            json={"name": "待删除"},
            headers={"X-Token": server.token},
        )
        sid = create_resp.json()["data"]["id"]

        response = client.delete(
            f"/api/strategies/{sid}",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_delete_nonexistent(self, client, server):
        response = client.delete(
            "/api/strategies/nonexistent",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 404

    def test_toggle_strategy(self, client, server):
        create_resp = client.post(
            "/api/strategies",
            json={"name": "切换测试", "enabled": True},
            headers={"X-Token": server.token},
        )
        sid = create_resp.json()["data"]["id"]

        response = client.post(
            f"/api/strategies/{sid}/toggle",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["data"]["enabled"] is False

        response = client.post(
            f"/api/strategies/{sid}/toggle",
            headers={"X-Token": server.token},
        )
        assert response.json()["data"]["enabled"] is True

    def test_toggle_nonexistent(self, client, server):
        response = client.post(
            "/api/strategies/nonexistent/toggle",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 404

    def test_refresh_strategies(self, client, server):
        response = client.post(
            "/api/strategies/refresh",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_strategies_require_auth(self, client):
        response = client.get("/api/strategies")
        assert response.status_code == 422

    def test_strategies_invalid_token(self, client):
        response = client.get(
            "/api/strategies",
            headers={"X-Token": "bad-token"},
        )
        assert response.status_code == 401


class TestJukuanOrderAPI:
    """聚宽下单 API 端点测试"""

    def test_jukuan_order_buy(self, client, server):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["direction"] == "buy"

    def test_jukuan_order_sell(self, client, server):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": -100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["direction"] == "sell"

    def test_jukuan_order_missing_security(self, client, server):
        response = client.post(
            "/api/jukuan_order",
            json={"amount": 100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 400
        assert "请提供 security" in response.json()["detail"]

    def test_jukuan_order_target(self, client, server):
        response = client.post(
            "/api/jukuan_order_target",
            json={"security": "000001.XSHE", "amount": 200},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_value_no_position(self, client, server):
        response = client.post(
            "/api/jukuan_order_value",
            json={"security": "000001.XSHE", "value": 5000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 500

    def test_jukuan_order_target_value_no_position(self, client, server):
        response = client.post(
            "/api/jukuan_order_target_value",
            json={"security": "000001.XSHE", "value": 10000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 500

    def test_jukuan_order_requires_auth(self, client):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
        )
        assert response.status_code == 422


class TestReceiveSignal:
    """接收外部信号 API 测试"""

    def test_receive_signal_with_main_token(self, client, server):
        response = client.post(
            "/api/receive-signal",
            json={
                "signal_id": "sig-test-001",
                "stock_code": "000001.XSHE",
                "direction": "buy",
                "quantity": 100,
                "price": 10.0,
            },
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "order_id" in data["data"]

    def test_receive_signal_invalid_token(self, client):
        response = client.post(
            "/api/receive-signal",
            json={
                "signal_id": "sig-001",
                "stock_code": "000001.XSHE",
                "direction": "buy",
                "quantity": 100,
            },
            headers={"X-Token": "invalid"},
        )
        assert response.status_code == 401
