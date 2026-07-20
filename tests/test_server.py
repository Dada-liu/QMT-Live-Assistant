import sys
import os
import asyncio
import threading
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.server import QMTServer, create_server
from backend.order_tracker import OrderTracker


def _start_server(server):
    """在独立线程的事件循环中启动 QMTServer 的 watchdog，供同步 TestClient 使用。"""
    loop = asyncio.new_event_loop()
    server._test_loop = loop
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.init_and_setup_async())
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    for _ in range(100):
        if server.qmt_connected:
            break
        time.sleep(0.05)
    if not server.qmt_connected:
        raise RuntimeError("测试服务器未能连接到 QMT")
    return loop, thread


def _stop_server(server, loop, thread):
    """停止 watchdog 并清理后台线程。"""
    def schedule_stop():
        asyncio.create_task(server.stop_async())

    loop.call_soon_threadsafe(schedule_stop)
    for _ in range(50):
        if not server.running:
            break
        time.sleep(0.05)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)


@pytest.fixture
def server():
    srv = QMTServer(
        account_id="test_account",
        mini_qmt_path="/tmp/mock_qmt",
        host="0.0.0.0",
        port=8001,
    )
    loop, thread = _start_server(srv)
    yield srv
    _stop_server(srv, loop, thread)


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
    """聚宽下单 API 端点测试（仅支持策略 Token）"""

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "聚宽测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        return response.json()["data"]

    def test_jukuan_order_buy(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["direction"] == "buy"

    def test_jukuan_order_sell(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": -100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 500
        assert "策略可用持仓不足" in response.json()["detail"]

    def test_jukuan_order_missing_security(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 400
        assert "请提供 security" in response.json()["detail"]

    def test_jukuan_order_target(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order_target",
            json={"security": "000001.XSHE", "amount": 200},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_value(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order_value",
            json={"security": "000001.XSHE", "value": 5000},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_target_value(self, client, server):
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order_target_value",
            json={"security": "000001.XSHE", "value": 10000},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_jukuan_order_requires_auth(self, client):
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
        )
        assert response.status_code == 422

    def test_jukuan_order_rejects_master_token(self, client, server):
        """主 Token 不允许调用聚宽下单接口。"""
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 403
        assert "策略Token" in response.json()["detail"]


class TestOrdersApi:
    """订单查询 API 测试"""

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "订单查询测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        return response.json()["data"]

    def test_get_orders_empty(self, client, server):
        response = client.get(
            "/api/orders",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"] == []

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_get_orders_with_jukuan_order(self, mock_fetch_names, client, server):
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
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
        assert order["stock_name"] == "平安银行"

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_get_orders_stock_name_fallback(self, mock_fetch_names, client, server):
        mock_fetch_names.return_value = {}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
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
        assert order["stock_code"] == "000001.SZ"
        assert order["stock_name"] == ""

    def test_get_orders_filter_by_status(self, client, server):
        strategy = self._create_strategy(client, server)
        client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
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


from backend.connection_watchdog import ConnectionState


class TestConnectionState:
    def test_server_status_includes_connection_state(self, client, server):
        response = client.get("/api/server-status")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "qmt_connected" in data
        assert "connection_state" in data
        assert "last_connection_error" in data
        assert "reconnect_attempts" in data
        assert data["qmt_connected"] is True
        assert data["connection_state"] == ConnectionState.CONNECTED.value

    def test_account_asset_returns_503_when_disconnected(self, client, server):
        server._watchdog._state = ConnectionState.RECONNECTING
        response = client.get(
            "/api/account-asset",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 503
        assert "QMT 连接断开" in response.json()["detail"]
        server._watchdog._state = ConnectionState.CONNECTED

    def test_jukuan_order_returns_503_when_disconnected(self, client, server):
        strategy = self._create_strategy(client, server)
        server._watchdog._state = ConnectionState.RECONNECTING
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 503
        server._watchdog._state = ConnectionState.CONNECTED

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        return response.json()["data"]


class TestOrderTrackingIntegration:
    """订单跟踪与策略持仓同步集成测试"""

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "跟踪测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        return response.json()["data"]

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_jukuan_order_tracks_order(self, mock_fetch_names, client, server):
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]
        tracked = server.order_tracker.get_order(order_id)
        assert tracked is not None
        assert tracked.direction == "buy"
        assert tracked.stock_name == "平安银行"

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
        assert s.available_cash == 100000 - 1255

    def test_strategy_jukuan_order_optimistic_snapshot_persisted(self, client, server):
        """买入下单时应把乐观持仓快照写入订单对象。"""
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]

        tracked = server.order_tracker.get_order(order_id)
        assert tracked.optimistic_position_applied is True
        assert tracked.optimistic_snapshot is not None
        assert tracked.optimistic_snapshot.get("delta_cash") < 0

    def test_strategy_jukuan_order_failed_rolls_back_cash(self, client, server):
        """买入失败后应恢复策略可用资金。"""
        from backend.qmt_xtconstant import ORDER_CANCELED

        strategy = self._create_strategy(client, server)
        before_cash = server.strategy_manager.get(strategy["id"]).available_cash

        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]

        # 乐观扣除后资金减少
        after_place_cash = server.strategy_manager.get(strategy["id"]).available_cash
        assert after_place_cash < before_cash

        # 模拟撤单失败
        server.order_tracker.update_from_callback(
            order_id, ORDER_CANCELED, 0, 0.0
        )

        tracked = server.order_tracker.get_order(order_id)
        assert tracked.status == "failed"

        # 资金应恢复
        after_fail_cash = server.strategy_manager.get(strategy["id"]).available_cash
        assert after_fail_cash == before_cash

    def test_strategy_total_asset_includes_frozen_cash(self, client, server):
        """未成交买入订单的冻结资金应加回到 total_asset。"""
        from backend.qmt_xtconstant import ORDER_CANCELED

        strategy = self._create_strategy(client, server)

        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]

        # 未成交时 total_asset 应保持为初始分配资金
        list_resp = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        data = list_resp.json()["data"]
        strategy_data = next(s for s in data if s["id"] == strategy["id"])
        assert strategy_data["total_asset"] == strategy["allocated_funds"]
        assert strategy_data["frozen_cash"] == 1255

        # 失败后冻结资金释放，total_asset 仍保持
        server.order_tracker.update_from_callback(
            order_id, ORDER_CANCELED, 0, 0.0
        )

        list_resp = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        data = list_resp.json()["data"]
        strategy_data = next(s for s in data if s["id"] == strategy["id"])
        assert strategy_data["total_asset"] == strategy["allocated_funds"]
        assert strategy_data["frozen_cash"] == 0

    def test_strategy_frozen_cash_cleared_after_fill(self, client, server):
        """买入成交后 frozen_cash 应为 0，total_asset 按真实持仓计算。"""
        from backend.qmt_xtconstant import ORDER_SUCCEEDED

        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]

        server.order_tracker.update_from_callback(
            order_id, ORDER_SUCCEEDED, 100, 12.55
        )

        list_resp = client.get(
            "/api/strategies",
            headers={"X-Token": server.token},
        )
        data = list_resp.json()["data"]
        strategy_data = next(s for s in data if s["id"] == strategy["id"])
        assert strategy_data["frozen_cash"] == 0
        assert strategy_data["total_asset"] == 100000

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


class TestOrderCancelResendApi:
    """订单撤销与重发 API 测试"""

    def _create_strategy(self, client, server):
        response = client.post(
            "/api/strategies",
            json={"name": "撤销重发测试策略", "allocated_funds": 100000},
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        return response.json()["data"]

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_cancel_pending_order(self, mock_fetch_names, client, server):
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert response.status_code == 200
        order_id = response.json()["data"]["order_id"]

        cancel_resp = client.post(
            f"/api/orders/{order_id}/cancel",
            headers={"X-Token": server.token},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["data"]["status"] == "failed"

    def test_cancel_nonexistent_order(self, client, server):
        response = client.post(
            "/api/orders/nonexistent/cancel",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 404

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_cancel_filled_order_returns_400(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_SUCCEEDED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_SUCCEEDED, 100, 12.55)

        cancel_resp = client.post(
            f"/api/orders/{order_id}/cancel",
            headers={"X-Token": server.token},
        )
        assert cancel_resp.status_code == 400

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_failed_order(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 200
        data = resend_resp.json()["data"]
        assert data["direction"] == "buy"
        assert data["retried_from_order_id"] == str(order_id)

        original = server.order_tracker.get_order(order_id)
        assert original.retried_as_order_id == str(data["order_id"])

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_pending_order_returns_400(self, mock_fetch_names, client, server):
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 400
        assert "仅失败订单可重发" in resend_resp.json()["detail"]

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_already_retried_order_returns_400(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        first = client.post(
            f"/api/orders/{order_id}/resend",
            headers={"X-Token": server.token},
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/orders/{order_id}/resend",
            headers={"X-Token": server.token},
        )
        assert second.status_code == 400
        assert "已重发过" in second.json()["detail"]

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_with_overridden_quantity_and_price(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            json={"quantity": 200, "price": 11.5},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 200
        data = resend_resp.json()["data"]
        assert data["quantity"] == 200
        assert data["price"] == 11.5

        new_order = server.order_tracker.get_order(data["order_id"])
        assert new_order.quantity == 200
        assert new_order.price == 11.5

        # 原订单参数保持不变，仅记录重发链接
        original = server.order_tracker.get_order(order_id)
        assert original.quantity == 100
        assert original.retried_as_order_id == str(data["order_id"])

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_with_market_price_override(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            json={"price": 0},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 200
        data = resend_resp.json()["data"]
        assert data["price"] == 0.0

        new_order = server.order_tracker.get_order(data["order_id"])
        assert new_order.price == 0.0

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_buy_quantity_not_lot_multiple_returns_400(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            json={"quantity": 150},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 400
        assert "整数倍" in resend_resp.json()["detail"]

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_sell_odd_lot_allowed(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        # 先买入并成交，建立 100 股持仓
        buy_resp = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert buy_resp.status_code == 200

        import asyncio
        asyncio.run(server.order_tracker.poll_and_reconcile(server.trader, server.account))

        # 卖出 100 股并置为失败
        sell_resp = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": -100},
            headers={"X-Token": strategy["token"]},
        )
        assert sell_resp.status_code == 200
        sell_order_id = sell_resp.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(sell_order_id, ORDER_CANCELED, 0, 0.0)

        # 卖出允许零股，50 股应重发成功
        resend_resp = client.post(
            f"/api/orders/{sell_order_id}/resend",
            json={"quantity": 50},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 200
        data = resend_resp.json()["data"]
        assert data["quantity"] == 50

        new_order = server.order_tracker.get_order(data["order_id"])
        assert new_order.quantity == 50
        assert new_order.direction == "sell"

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_invalid_quantity_returns_422(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        for bad_quantity in (0, -100):
            resend_resp = client.post(
                f"/api/orders/{order_id}/resend",
                json={"quantity": bad_quantity},
                headers={"X-Token": server.token},
            )
            assert resend_resp.status_code == 422

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_invalid_price_returns_422(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        response = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        order_id = response.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(order_id, ORDER_CANCELED, 0, 0.0)

        resend_resp = client.post(
            f"/api/orders/{order_id}/resend",
            json={"price": -1},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 422

    @patch("backend.server.fetch_stock_names_from_xtdata")
    def test_resend_insufficient_position_returns_400(self, mock_fetch_names, client, server):
        from backend.qmt_xtconstant import ORDER_CANCELED
        mock_fetch_names.return_value = {"000001.SZ": "平安银行"}
        strategy = self._create_strategy(client, server)
        # 先买入并成交，建立 100 股持仓
        buy_resp = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": 100},
            headers={"X-Token": strategy["token"]},
        )
        assert buy_resp.status_code == 200

        import asyncio
        asyncio.run(server.order_tracker.poll_and_reconcile(server.trader, server.account))

        # 卖出 100 股并置为失败
        sell_resp = client.post(
            "/api/jukuan_order",
            json={"security": "000001.XSHE", "amount": -100},
            headers={"X-Token": strategy["token"]},
        )
        assert sell_resp.status_code == 200
        sell_order_id = sell_resp.json()["data"]["order_id"]
        server.order_tracker.update_from_callback(sell_order_id, ORDER_CANCELED, 0, 0.0)

        # 重发 200 股超出策略 100 股可用持仓，应返回 400
        resend_resp = client.post(
            f"/api/orders/{sell_order_id}/resend",
            json={"quantity": 200},
            headers={"X-Token": server.token},
        )
        assert resend_resp.status_code == 400
        assert "策略可用持仓不足" in resend_resp.json()["detail"]

    def test_cancel_returns_503_when_disconnected(self, client, server):
        server._watchdog._state = ConnectionState.RECONNECTING
        response = client.post(
            "/api/orders/100001/cancel",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 503
        server._watchdog._state = ConnectionState.CONNECTED

    def test_resend_returns_503_when_disconnected(self, client, server):
        server._watchdog._state = ConnectionState.RECONNECTING
        response = client.post(
            "/api/orders/100001/resend",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 503
        server._watchdog._state = ConnectionState.CONNECTED


class TestMarketOpenPoll:
    def test_market_open_poll_task_created(self, server):
        assert server._market_open_poll_task is not None
        assert not server._market_open_poll_task.done()


class TestServerLifecycle:
    def test_init_and_setup_sync_lifecycle(self):
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8004)
        try:
            srv.init_and_setup()
            assert srv.running is True
            assert srv.qmt_connected is True
        finally:
            srv.stop()
        assert srv.running is False

    def test_stop_without_running_loop(self):
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8005)
        srv.stop()
        assert srv.running is False

    def test_stop_async_directly(self):
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8006)

        async def dummy_task():
            while True:
                await asyncio.sleep(1)

        async def run():
            srv.running = True
            srv._poll_task = asyncio.create_task(dummy_task())
            srv._market_open_poll_task = asyncio.create_task(dummy_task())
            await srv.stop_async()

        asyncio.run(run())
        assert srv.running is False
        assert srv._poll_task is None
        assert srv._market_open_poll_task is None

    @pytest.mark.asyncio
    async def test_market_open_poll_loop_triggers_reconcile(self):
        from unittest.mock import AsyncMock, patch as local_patch
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8007)
        srv.running = True

        class FakeWatchdog:
            connected = True
            trader = None
            account = None

        srv._watchdog = FakeWatchdog()

        with local_patch("backend.server.seconds_until_market_open", return_value=0.001):
            with local_patch.object(srv.order_tracker, "poll_and_reconcile", new=AsyncMock()):
                task = asyncio.create_task(srv._market_open_poll_loop())
                await asyncio.sleep(0.01)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    def test_ensure_account_record_creates_new_account(self):
        from unittest.mock import MagicMock
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8008)
        repo = MagicMock()
        repo.get_by_account_id.return_value = None
        srv._account_repository = repo
        srv._db_session = object()
        srv._ensure_account_record()
        assert repo.add.called
        args = repo.add.call_args[0]
        assert args[0].account_id == "test_account"
        assert args[0].qmt_path == "/tmp/mock_qmt"

    def test_ensure_account_record_updates_existing_account(self):
        from unittest.mock import MagicMock
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8009)
        existing = MagicMock()
        repo = MagicMock()
        repo.get_by_account_id.return_value = existing
        srv._account_repository = repo
        srv._db_session = object()
        srv._ensure_account_record()
        assert existing.qmt_path == "/tmp/mock_qmt"
        assert repo.update.called

    def test_signal_logs_returns_empty_without_repository(self, client, server):
        server._signal_log_repository = None
        response = client.get(
            "/api/signal-logs",
            headers={"X-Token": server.token},
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_stop_with_running_loop(self):
        srv = create_server("test_account", "/tmp/mock_qmt", "0.0.0.0", 8010)

        async def dummy_task():
            while True:
                await asyncio.sleep(1)

        async def run():
            srv.running = True
            srv._poll_task = asyncio.create_task(dummy_task())
            srv.stop()

        asyncio.run(run())
        assert srv.running is False
