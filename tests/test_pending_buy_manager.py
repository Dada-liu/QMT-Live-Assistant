"""挂起买单管理器异常分级测试。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from backend.db.models.pending_buy_order import (
    PendingBuyOrderModel,
    PENDING_BUY_WAITING,
    PENDING_BUY_FAILED,
)
from backend.db.repositories.pending_buy import InMemoryPendingBuyRepository
from backend.jukuan_orders import (
    InsufficientFundsError,
    ReferencePriceUnavailableError,
)
from backend.pending_buy_manager import PendingBuyManager


def _make_manager(handler=None):
    strategy_manager = MagicMock()
    strategy = MagicMock()
    strategy.enabled = True
    strategy.name = "测试策略"
    strategy_manager.get.return_value = strategy

    order_tracker = MagicMock()
    order_tracker.get_orders_by_strategy.return_value = []

    repo = InMemoryPendingBuyRepository()
    return PendingBuyManager(
        strategy_manager=strategy_manager,
        order_tracker=order_tracker,
        repository=repo,
        handler_factory=lambda: handler or MagicMock(),
    )


def _make_pending(method_name="jukuan_order", amount=1000):
    now = datetime.now(timezone.utc)
    return PendingBuyOrderModel(
        id="pb1",
        strategy_id="strat1",
        method_name=method_name,
        stock_code="000001.SZ",
        request_payload={"security": "000001.XSHE", "amount": amount},
        status=PENDING_BUY_WAITING,
        reason="资金不足",
        created_at=now,
        expire_at=now + timedelta(minutes=30),
    )


class TestPendingBuyRetryExceptionClassification:
    """重试挂起买单时，永久异常应 fail-fast，瞬时异常应保持 waiting。"""

    def test_insufficient_funds_keeps_waiting(self):
        """资金不足时保持 waiting，不修改状态。"""
        handler = MagicMock()
        handler.jukuan_order.side_effect = InsufficientFundsError("资金不足")
        mgr = _make_manager(handler)
        pb = _make_pending()
        mgr._repo.add(pb)

        mgr.process_all()

        updated = mgr._repo.get(pb.id)
        assert updated.status == PENDING_BUY_WAITING
        assert updated.resolved_at is None

    def test_value_error_fails_fast(self):
        """ValueError（永久异常）应标记为 failed，不再重试。"""
        handler = MagicMock()
        handler.jukuan_order.side_effect = ValueError("券种校验失败")
        mgr = _make_manager(handler)
        pb = _make_pending()
        mgr._repo.add(pb)

        mgr.process_all()

        updated = mgr._repo.get(pb.id)
        assert updated.status == PENDING_BUY_FAILED
        assert "永久异常" in updated.reason
        assert "券种校验失败" in updated.reason

    def test_reference_price_unavailable_keeps_waiting(self):
        """行情参考价不可用是瞬时异常，应保持 waiting 并向上传播。"""
        handler = MagicMock()
        handler.jukuan_order.side_effect = ReferencePriceUnavailableError("行情不可用")
        mgr = _make_manager(handler)
        pb = _make_pending()
        mgr._repo.add(pb)

        # process_all 会捕获单个异常并记录日志，但不改变状态
        mgr.process_all()

        updated = mgr._repo.get(pb.id)
        assert updated.status == PENDING_BUY_WAITING
        assert updated.resolved_at is None
