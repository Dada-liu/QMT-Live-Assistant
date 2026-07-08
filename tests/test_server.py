import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
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
        positions = data["data"].get("positions", [])
        if positions:
            pos = positions[0]
            assert "stock_name" in pos
            assert "open_price" in pos
            assert "total_pnl" in pos
            assert "can_use_volume" in pos
            assert "current_price" not in pos

    def test_signals_endpoint_removed(self, client, server):
        response = client.get(
            "/api/signals",
            headers={"X-Token": server.token}
        )
        assert response.status_code == 404


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
            json={"name": "策略A", "allocated_funds": 10000},
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
            json={"name": "原始名称", "allocated_funds": 10000},
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
            json={"name": "待删除", "allocated_funds": 10000},
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
            json={"name": "切换测试", "allocated_funds": 10000, "enabled": True},
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

    def test_create_strategy_normalizes_jq_code(self, client, server):
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata", return_value={"000001.SZ": 12.0}):
            response = client.post(
                "/api/strategies",
                json={
                    "name": "归一化测试",
                    "allocated_funds": 100000,
                    "positions": [
                        {"stock_code": "000001.XSHE", "stock_name": "平安银行", "quantity": 100, "current_price": 12.0}
                    ],
                },
                headers={"X-Token": server.token},
            )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["positions"]) == 1
        assert data["positions"][0]["stock_code"] == "000001.SZ"

    def test_update_strategy_normalizes_jq_code(self, client, server):
        create_resp = client.post(
            "/api/strategies",
            json={"name": "原始策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        sid = create_resp.json()["data"]["id"]

        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata", return_value={"000001.SZ": 12.0}):
            response = client.put(
                f"/api/strategies/{sid}",
                json={
                    "positions": [
                        {"stock_code": "000001.XSHE", "stock_name": "平安银行", "quantity": 100, "current_price": 12.0}
                    ],
                },
                headers={"X-Token": server.token},
            )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["positions"]) == 1
        assert data["positions"][0]["stock_code"] == "000001.SZ"

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

    def test_jukuan_order_value(self, client, server):
        response = client.post(
            "/api/jukuan_order_value",
            json={"security": "000001.XSHE", "value": 5000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_target_value(self, client, server):
        response = client.post(
            "/api/jukuan_order_target_value",
            json={"security": "000001.XSHE", "value": 10000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_requires_auth(self, client):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
        )
        assert response.status_code == 422


class TestOrdersApi:
    """订单查询 API 测试"""

    def test_get_orders_empty(self, client, server):
        response = client.get(
            "/api/orders",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []

    def test_get_orders_with_jukuan_order(self, client, server):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200

        response = client.get(
            "/api/orders",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) == 1
        order = data["data"][0]
        assert order["direction"] == "buy"
        assert order["status"] == "pending"
        assert order["jq_code"] == "000001.XSHE"
        assert order["stock_code"] == "000001.SZ"

    def test_get_orders_filter_by_status(self, client, server):
        client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": server.token},
        )

        response = client.get(
            "/api/orders?status=pending",
            headers={"X-Token": server.token},
        )
        data = response.json()
        assert len(data["data"]) == 1

        response = client.get(
            "/api/orders?status=filled",
            headers={"X-Token": server.token},
        )
        data = response.json()
        assert len(data["data"]) == 0

    def test_get_orders_unauthorized(self, client):
        response = client.get("/api/orders")
        assert response.status_code == 422


class TestOrderTrackingIntegration:
    """订单跟踪与策略持仓同步集成测试"""

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "跟踪测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        return response.json()["data"]

    def test_jukuan_order_tracks_order(self, client, server):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]
        tracked = server.order_tracker.get_order(order_id)
        assert tracked is not None
        assert tracked.direction == "buy"

    def test_strategy_jukuan_order_optimistic_update(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        s = server.strategy_manager.get(strategy["id"])
        # 买入未成交前不创建 position 行，仅资金被冻结
        assert len(s.positions) == 0

    def test_strategy_jukuan_order_resolves_on_poll(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]

        import asyncio
        asyncio.run(server.order_tracker.poll_and_reconcile(server.trader, server.account))

        tracked = server.order_tracker.get_order(order_id)
        assert tracked.status == "filled"
        s = server.strategy_manager.get(strategy["id"])
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["stock_code"] == "000001.SZ"
        assert s.available_cash == 100000 - 1250

    def test_strategy_order_count_replaces_signal_count(self, client, server):
        strategy = self._create_strategy(client, server)
        client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        response = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        strategy_data = next(s for s in data if s["id"] == strategy["id"])
        assert "signal_count" not in strategy_data
        assert strategy_data["order_count"] == 1

    def test_strategy_two_pending_orders_same_stock(self, client, server):
        """同一策略 token 对同一只股票连续下两单，第一单成交后第二单冻结应保留。"""
        from backend.qmt_xtconstant import ORDER_SUCCEEDED

        strategy = self._create_strategy(client, server)

        response_a = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response_a.status_code == 200
        order_id_a = response_a.json()["data"]["order_id"]

        response_b = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response_b.status_code == 200
        order_id_b = response_b.json()["data"]["order_id"]

        # 两单均为 pending，买入未成交前不创建 position 行
        s = server.strategy_manager.get(strategy["id"])
        assert len(s.positions) == 0

        # 手动驱动第一单成交（模拟 QMT 回调）
        server.order_tracker.update_from_callback(
            order_id_a, ORDER_SUCCEEDED, 100, 12.50
        )

        tracked_a = server.order_tracker.get_order(order_id_a)
        assert tracked_a.status == "filled"

        # 第一单成交后创建 position
        s = server.strategy_manager.get(strategy["id"])
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["available_quantity"] == 100
        assert s.positions[0]["frozen_quantity"] == 0

        # 手动驱动第二单成交
        server.order_tracker.update_from_callback(
            order_id_b, ORDER_SUCCEEDED, 100, 12.50
        )

        tracked_b = server.order_tracker.get_order(order_id_b)
        assert tracked_b.status == "filled"

        s = server.strategy_manager.get(strategy["id"])
        assert s.positions[0]["quantity"] == 200
        assert s.positions[0]["available_quantity"] == 200
        assert s.positions[0]["frozen_quantity"] == 0

    def test_strategy_jukuan_order_target_uses_strategy_quantity(self, client, server):
        """策略 token 调仓应基于策略自身持仓，而非账户持仓。"""
        from backend.models.strategy import PositionAssignment

        strategy = self._create_strategy(client, server)
        # 给策略分配 300 股，与 mock 账户的 100 股不同
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata", return_value={"000001.SZ": 12.0}):
            client.put(
                f"/api/strategies/{strategy['id']}",
                json={
                    "positions": [
                        {
                            "stock_code": "000001.XSHE",
                            "stock_name": "平安银行",
                            "quantity": 300,
                            "current_price": 12.0,
                        }
                    ]
                },
                headers={"X-Token": server.token},
            )

        response = client.post(
            "/api/jukuan_order_target",
            json={"security": "000001.XSHE", "amount": 500},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["direction"] == "buy"
        assert data["quantity"] == 200

    def test_strategy_jukuan_order_value_capped_by_strategy_cash(self, client, server):
        """策略 token 按金额买入不应超出策略可用资金。"""
        strategy = self._create_strategy(client, server)
        # 策略可用资金 100000，mock 行情价格 12.55，最多买 7900 股（按手数 100 取整）
        response = client.post(
            "/api/jukuan_order_value",
            json={"security": "000001.XSHE", "value": 200000},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["direction"] == "buy"
        assert data["quantity"] == 7900

    def test_strategy_jukuan_order_sell_rejected_without_position(self, client, server):
        """无持仓策略 token 卖出应被拒绝。"""
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": -100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 500
        assert "策略可用持仓不足" in response.json()["detail"]
