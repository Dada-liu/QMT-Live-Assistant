"""挂起买单 Repository 测试。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.models.pending_buy_order import (
    PendingBuyOrderModel,
    PENDING_BUY_WAITING,
    PENDING_BUY_SUBMITTED,
    PENDING_BUY_EXPIRED,
)
from backend.db.repositories.pending_buy import (
    InMemoryPendingBuyRepository,
    SQLAlchemyPendingBuyRepository,
)

import pytest


def _make_order(order_id="pb1", status=PENDING_BUY_WAITING, created_at=None):
    now = datetime.now(timezone.utc)
    return PendingBuyOrderModel(
        id=order_id,
        strategy_id="strat1",
        method_name="jukuan_order",
        stock_code="000001.SZ",
        request_payload={"security": "000001.XSHE", "amount": 1000},
        status=status,
        reason="资金不足",
        created_at=created_at or now,
        expire_at=now + timedelta(minutes=30),
    )


@pytest.fixture(params=["memory", "sqlalchemy"])
def repo(request, tmp_path):
    if request.param == "memory":
        return InMemoryPendingBuyRepository()
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return SQLAlchemyPendingBuyRepository(sessionmaker(bind=engine)())


class TestPendingBuyRepository:
    def test_add_and_get(self, repo):
        repo.add(_make_order())
        loaded = repo.get("pb1")
        assert loaded is not None
        assert loaded.strategy_id == "strat1"
        assert loaded.status == PENDING_BUY_WAITING
        assert loaded.request_payload["amount"] == 1000
        # 时间字段带 UTC 时区
        assert loaded.expire_at.tzinfo is not None

    def test_update_status(self, repo):
        repo.add(_make_order())
        loaded = repo.get("pb1")
        loaded.status = PENDING_BUY_SUBMITTED
        loaded.submitted_order_id = "100001"
        loaded.resolved_at = datetime.now(timezone.utc)
        repo.update(loaded)
        reloaded = repo.get("pb1")
        assert reloaded.status == PENDING_BUY_SUBMITTED
        assert reloaded.submitted_order_id == "100001"

    def test_list_waiting_ordered_by_created_at(self, repo):
        now = datetime.now(timezone.utc)
        repo.add(_make_order("pb_a", created_at=now + timedelta(seconds=2)))
        repo.add(_make_order("pb_b", created_at=now))
        repo.add(_make_order("pb_c", status=PENDING_BUY_EXPIRED, created_at=now - timedelta(seconds=5)))
        waiting = repo.list_waiting()
        assert [e.id for e in waiting] == ["pb_b", "pb_a"]

    def test_delete(self, repo):
        repo.add(_make_order())
        assert repo.delete("pb1") is True
        assert repo.get("pb1") is None
        assert repo.delete("pb1") is False
