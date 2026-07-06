import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.repositories.strategy import SQLAlchemyStrategyRepository, InMemoryStrategyRepository
from backend.models.strategy import Strategy, StrategyCreate
from backend.strategy_manager import StrategyManager


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestSQLAlchemyStrategyRepository:
    def test_save_and_get_by_id(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = Strategy(name="测试策略", allocated_funds=100000)
        saved = repo.save(strategy)
        found = repo.get_by_id(saved.id)
        assert found is not None
        assert found.name == "测试策略"
        assert found.allocated_funds == 100000
        assert len(found.token) == 32

    def test_get_by_token(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = Strategy(name="Token测试", token="abc123", allocated_funds=10000)
        repo.save(strategy)
        found = repo.get_by_token("abc123")
        assert found is not None
        assert found.name == "Token测试"
        assert found.token == "abc123"

    def test_list_all_excludes_deleted(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        s1 = repo.save(Strategy(name="启用", allocated_funds=10000))
        s2 = repo.save(Strategy(name="删除", allocated_funds=10000))
        repo.delete(s2.id)
        all_strategies = repo.list_all()
        assert len(all_strategies) == 1
        assert all_strategies[0].name == "启用"

    def test_delete_is_soft_delete(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = repo.save(Strategy(name="待删除", allocated_funds=10000))
        assert repo.delete(strategy.id) is True
        assert repo.get_by_id(strategy.id) is None
        all_including_disabled = repo.list_all(include_disabled=True)
        assert len(all_including_disabled) == 1
        assert all_including_disabled[0].deleted_at is not None

    def test_save_updates_positions(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = Strategy(
            name="持仓测试",
            allocated_funds=100000,
            available_cash=90000,
            positions=[{"stock_code": "000001.SZ", "stock_name": "平安", "quantity": 100, "avg_cost": 10.0}],
        )
        saved = repo.save(strategy)
        found = repo.get_by_id(saved.id)
        assert len(found.positions) == 1
        assert found.positions[0]["stock_code"] == "000001.SZ"

    def test_save_persists_frozen_quantity(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = Strategy(
            name="冻结测试",
            allocated_funds=100000,
            available_cash=90000,
            positions=[{
                "stock_code": "000001.SZ",
                "stock_name": "平安",
                "quantity": 100,
                "available_quantity": 60,
                "frozen_quantity": 40,
                "avg_cost": 10.0,
            }],
        )
        repo.save(strategy)
        found = repo.get_by_id(strategy.id)
        assert found.positions[0]["quantity"] == 100
        assert found.positions[0]["available_quantity"] == 60
        assert found.positions[0]["frozen_quantity"] == 40


class TestInMemoryStrategyRepository:
    def test_save_and_get_by_token(self):
        repo = InMemoryStrategyRepository()
        strategy = Strategy(name="内存测试", token="mem-token", allocated_funds=10000)
        repo.save(strategy)
        found = repo.get_by_token("mem-token")
        assert found is not None
        assert found.name == "内存测试"


class TestStrategyManagerWithSQLAlchemyRepository:
    def test_create_and_update_position(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        mgr = StrategyManager(repository=repo)
        strategy = mgr.create(StrategyCreate(name="集成测试", allocated_funds=100000))
        mgr.update_position(strategy.id, "000001.SZ", "buy", 100, 10.0)

        found = mgr.get(strategy.id)
        assert len(found.positions) == 1
        assert found.positions[0]["quantity"] == 100
        assert found.available_cash == 100000 - 1000

    def test_optimistic_update_and_rollback(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        mgr = StrategyManager(repository=repo)
        strategy = mgr.create(StrategyCreate(name="乐观测试", allocated_funds=100000))
        snapshot = mgr.apply_optimistic_position(strategy.id, "000001.SZ", "buy", 100, 10.0)

        assert snapshot is not None
        assert snapshot["quantity"] == 0

        mgr.rollback_position(strategy.id, snapshot)
        found = mgr.get(strategy.id)
        assert len(found.positions) == 0
        assert found.available_cash == 100000
