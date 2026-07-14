import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.order_tracker import OrderTracker, OrderState, TrackedOrder
from backend.db.repositories.order import InMemoryOrderRepository
from backend.qmt_xtconstant import (
    ORDER_REPORTED,
    ORDER_PART_SUCC,
    ORDER_SUCCEEDED,
    ORDER_CANCELED,
    ORDER_JUNK,
)


class TestOrderTracker:
    @pytest.fixture
    def tracker(self):
        return OrderTracker()

    def _track_sample(self, tracker, order_id="100001"):
        return tracker.track_order(
            order_id=order_id,
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="abc123",
            strategy_name="测试策略",
            price=10.0,
            optimistic_position_applied=True,
        )

    def test_track_new_order(self, tracker):
        order = self._track_sample(tracker)
        assert order.status == OrderState.PENDING
        assert order.order_id == "100001"
        assert tracker.get_order("100001") == order

    def test_callback_reported_keeps_pending(self, tracker):
        self._track_sample(tracker)
        updated = tracker.update_from_callback("100001", ORDER_REPORTED)
        assert updated.status == OrderState.PENDING

    def test_callback_filled(self, tracker):
        self._track_sample(tracker)
        updated = tracker.update_from_callback("100001", ORDER_SUCCEEDED)
        assert updated.status == OrderState.FILLED
        assert updated.resolved_at is not None

    def test_callback_rejected(self, tracker):
        self._track_sample(tracker)
        updated = tracker.update_from_callback("100001", ORDER_JUNK)
        assert updated.status == OrderState.FAILED

    def test_callback_cancelled_no_fill(self, tracker):
        self._track_sample(tracker)
        updated = tracker.update_from_callback("100001", ORDER_CANCELED)
        assert updated.status == OrderState.FAILED

    def test_callback_cancelled_with_partial_fill(self, tracker):
        order = self._track_sample(tracker)
        tracker.update_from_trade("100001", 30, 10.0)
        assert order.status == OrderState.PARTIAL
        updated = tracker.update_from_callback("100001", ORDER_CANCELED)
        assert updated.status == OrderState.FILLED
        assert updated.filled_quantity == 30

    def test_trade_callback_partial_then_filled(self, tracker):
        order = self._track_sample(tracker)
        tracker.update_from_trade("100001", 40, 10.0)
        assert order.status == OrderState.PARTIAL
        tracker.update_from_trade("100001", 60, 10.2)
        assert order.status == OrderState.FILLED
        assert order.filled_quantity == 100
        assert order.filled_price == round((40 * 10.0 + 60 * 10.2) / 100, 4)

    def test_error_callback(self, tracker):
        self._track_sample(tracker)
        updated = tracker.update_from_error("100001", "资金不足")
        assert updated.status == OrderState.FAILED
        assert updated.error_msg == "资金不足"

    def test_state_change_callback(self, tracker):
        called = []

        def on_change(order):
            called.append(order.order_id)

        tracker.on_state_change(on_change)
        self._track_sample(tracker)
        tracker.update_from_callback("100001", ORDER_SUCCEEDED)
        assert "100001" in called

    def test_idempotent_resolve(self, tracker):
        self._track_sample(tracker)
        tracker.update_from_callback("100001", ORDER_SUCCEEDED)
        first_resolved_at = tracker.get_order("100001").resolved_at
        tracker.update_from_callback("100001", ORDER_SUCCEEDED)
        assert tracker.get_order("100001").resolved_at == first_resolved_at

    def test_get_pending_orders(self, tracker):
        self._track_sample(tracker, "100001")
        tracker.track_order(
            order_id="100002",
            stock_code="000002.SZ",
            jq_code="000002.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id=None,
            strategy_name="",
            price=10.0,
        )
        tracker.update_from_callback("100002", ORDER_SUCCEEDED)
        pending = tracker.get_pending_orders()
        assert len(pending) == 1
        assert pending[0].order_id == "100001"

    def test_get_orders_by_strategy(self, tracker):
        self._track_sample(tracker, "100001")
        tracker.track_order(
            order_id="100002",
            stock_code="000002.SZ",
            jq_code="000002.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="other",
            strategy_name="其他",
            price=10.0,
        )
        orders = tracker.get_orders_by_strategy("abc123")
        assert len(orders) == 1
        assert orders[0].order_id == "100001"


class TestOrderTrackerLogging:
    @pytest.fixture
    def tracker(self):
        return OrderTracker()

    def _track_sample(self, tracker, order_id="100001"):
        return tracker.track_order(
            order_id=order_id,
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="abc123",
            strategy_name="测试策略",
            price=10.0,
            optimistic_position_applied=True,
        )

    def test_track_order_logs(self, tracker, caplog):
        with caplog.at_level("INFO"):
            self._track_sample(tracker)
        assert "新订单" in caplog.text
        assert "100001" in caplog.text

    def test_filled_logs(self, tracker, caplog):
        self._track_sample(tracker)
        with caplog.at_level("INFO"):
            tracker.update_from_callback("100001", ORDER_SUCCEEDED)
        assert "订单成交" in caplog.text
        assert "测试策略" in caplog.text

    def test_failed_logs(self, tracker, caplog):
        self._track_sample(tracker)
        with caplog.at_level("WARNING"):
            tracker.update_from_error("100001", "资金不足")
        assert "订单失败" in caplog.text
        assert "资金不足" in caplog.text

    def test_partial_logs(self, tracker, caplog):
        self._track_sample(tracker)
        with caplog.at_level("INFO"):
            tracker.update_from_trade("100001", 40, 10.0)
        assert "部分成交" in caplog.text
        assert "40/100" in caplog.text


class TestOrderTrackerPoll:
    @pytest.fixture
    def tracker(self):
        return OrderTracker()

    @pytest.fixture
    def mock_trader(self):
        class MockTrader:
            def __init__(self):
                self._orders = {}
                self._counter = 100000

            def order_stock(self, **kwargs):
                self._counter += 1
                order = type("O", (), {})()
                order.order_id = self._counter
                order.order_status = 50
                order.traded_volume = 0
                order.traded_price = 0.0
                self._orders[str(self._counter)] = order
                return self._counter

            def _advance(self, o):
                if o.order_status == 50:
                    o.order_status = 56
                    o.traded_volume = 100
                    o.traded_price = 10.0

            def query_stock_order(self, account, order_id):
                o = self._orders.get(str(order_id))
                if o:
                    self._advance(o)
                return o

            def query_stock_orders(self, account, cancelable_only=False):
                for o in self._orders.values():
                    self._advance(o)
                return list(self._orders.values())

        return MockTrader()

    @pytest.mark.asyncio
    async def test_poll_resolves_pending(self, tracker, mock_trader):
        oid = mock_trader.order_stock()
        tracker.track_order(
            order_id=oid,
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id=None,
            strategy_name="",
            price=10.0,
        )
        resolved = await tracker.poll_and_reconcile(mock_trader, None)
        assert len(resolved) == 1
        assert resolved[0].status == OrderState.FILLED
        assert tracker.get_order(str(oid)).status == OrderState.FILLED


class TestOrderTrackerLoadHistory:
    def test_loads_filled_orders_on_init(self):
        repo = InMemoryOrderRepository()
        repo.save(TrackedOrder(
            order_id="100001",
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="abc",
            strategy_name="测试策略",
            price=10.0,
            status=OrderState.FILLED,
        ))

        tracker = OrderTracker(repository=repo)
        orders = tracker.list_all()
        assert len(orders) == 1
        assert orders[0].order_id == "100001"
        assert orders[0].status == OrderState.FILLED

    def test_loads_pending_and_filled_orders(self):
        repo = InMemoryOrderRepository()
        repo.save(TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
            status=OrderState.PENDING,
        ))
        repo.save(TrackedOrder(
            order_id="100002", stock_code="000002.SZ", jq_code="000002.XSHE",
            direction="sell", quantity=100, order_type=24,
            strategy_id="abc", strategy_name="测试策略", price=12.0,
            status=OrderState.FAILED,
        ))

        tracker = OrderTracker(repository=repo)
        orders = tracker.list_all()
        assert len(orders) == 2
        assert tracker.get_pending_orders()[0].order_id == "100001"

    def test_loads_pending_order_with_optimistic_snapshot(self):
        repo = InMemoryOrderRepository()
        repo.save(TrackedOrder(
            order_id="100001",
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="abc",
            strategy_name="测试策略",
            price=10.0,
            status=OrderState.PENDING,
            optimistic_position_applied=True,
            optimistic_snapshot={"delta_quantity": 0, "delta_cash": -1000.0},
        ))

        tracker = OrderTracker(repository=repo)
        loaded = tracker.get_order("100001")
        assert loaded.optimistic_position_applied is True
        assert loaded.optimistic_snapshot == {"delta_quantity": 0, "delta_cash": -1000.0}