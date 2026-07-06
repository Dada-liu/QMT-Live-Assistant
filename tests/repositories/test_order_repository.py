import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.repositories.order import SQLAlchemyOrderRepository, InMemoryOrderRepository
from backend.db.repositories.account import SQLAlchemyAccountRepository
from backend.db.models.account import AccountModel
from backend.models.order import TrackedOrder, OrderState


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    account_repo = SQLAlchemyAccountRepository(session)
    account_repo.add(AccountModel(account_id="test_account", qmt_path="/tmp"))
    yield session
    session.close()


class TestSQLAlchemyOrderRepository:
    def test_save_and_get_by_id(self, db_session):
        repo = SQLAlchemyOrderRepository(db_session)
        order = TrackedOrder(
            order_id="100001",
            stock_code="000001.SZ",
            jq_code="000001.XSHE",
            direction="buy",
            quantity=100,
            order_type=23,
            strategy_id="abc",
            strategy_name="测试策略",
            price=10.0,
        )
        saved = repo.save(order)
        found = repo.get_by_id(saved.order_id)
        assert found is not None
        assert found.order_id == "100001"
        assert found.status == OrderState.PENDING

    def test_list_pending(self, db_session):
        repo = SQLAlchemyOrderRepository(db_session)
        pending_order = TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
            status=OrderState.PENDING,
        )
        filled_order = TrackedOrder(
            order_id="100002", stock_code="000002.SZ", jq_code="000002.XSHE",
            direction="sell", quantity=100, order_type=24,
            strategy_id="abc", strategy_name="测试策略", price=12.0,
            status=OrderState.FILLED,
        )
        repo.save(pending_order)
        repo.save(filled_order)

        pending = repo.list_pending()
        assert len(pending) == 1
        assert pending[0].order_id == "100001"

    def test_update_status_and_record_event(self, db_session):
        repo = SQLAlchemyOrderRepository(db_session)
        order = TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
        )
        repo.save(order)

        order.status = OrderState.FILLED
        order.filled_quantity = 100
        order.filled_price = 10.0
        repo.save(order)
        repo.record_event(
            order_id=order.order_id,
            event_type="filled",
            from_status=OrderState.PENDING,
            to_status=OrderState.FILLED,
            payload={"filled_quantity": 100},
            source="callback",
        )

        found = repo.get_by_id("100001")
        assert found.status == OrderState.FILLED

    def test_list_all_includes_filled(self, db_session):
        repo = SQLAlchemyOrderRepository(db_session)
        pending_order = TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
            status=OrderState.PENDING,
        )
        filled_order = TrackedOrder(
            order_id="100002", stock_code="000002.SZ", jq_code="000002.XSHE",
            direction="sell", quantity=100, order_type=24,
            strategy_id="abc", strategy_name="测试策略", price=12.0,
            status=OrderState.FILLED,
        )
        repo.save(pending_order)
        repo.save(filled_order)

        all_orders = repo.list_all()
        assert len(all_orders) == 2
        assert {o.order_id for o in all_orders} == {"100001", "100002"}

    def test_list_all_with_limit(self, db_session):
        repo = SQLAlchemyOrderRepository(db_session)
        for i in range(5):
            repo.save(TrackedOrder(
                order_id=f"10000{i}", stock_code=f"00000{i}.SZ", jq_code=f"00000{i}.XSHE",
                direction="buy", quantity=100, order_type=23,
                strategy_id="abc", strategy_name="测试策略", price=10.0,
            ))

        limited = repo.list_all(limit=2)
        assert len(limited) == 2

class TestInMemoryOrderRepository:
    def test_save_and_list_pending(self):
        repo = InMemoryOrderRepository()
        order = TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
        )
        repo.save(order)
        pending = repo.list_pending()
        assert len(pending) == 1

    def test_list_all(self):
        repo = InMemoryOrderRepository()
        repo.save(TrackedOrder(
            order_id="100001", stock_code="000001.SZ", jq_code="000001.XSHE",
            direction="buy", quantity=100, order_type=23,
            strategy_id="abc", strategy_name="测试策略", price=10.0,
            status=OrderState.FILLED,
        ))
        all_orders = repo.list_all()
        assert len(all_orders) == 1
        assert all_orders[0].status == OrderState.FILLED