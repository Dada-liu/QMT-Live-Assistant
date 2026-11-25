import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.models.strategy import StrategyModel
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
        all_including_deleted = repo.list_all(include_deleted=True)
        assert len(all_including_deleted) == 1
        assert all_including_deleted[0].deleted_at is not None

    def test_list_all_include_disabled_does_not_include_deleted(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        s1 = repo.save(Strategy(name="保留", allocated_funds=10000))
        s2 = repo.save(Strategy(name="删除", allocated_funds=10000))
        assert repo.delete(s2.id) is True

        # 默认查询：既不禁用也不删除
        default_list = repo.list_all()
        assert len(default_list) == 1
        assert default_list[0].id == s1.id

        # include_disabled=True 应包含禁用策略，但不包含已删除策略
        disabled_included = repo.list_all(include_disabled=True)
        assert len(disabled_included) == 1
        assert disabled_included[0].id == s1.id
        assert all(s.deleted_at is None for s in disabled_included)

        # include_deleted=True 才能看到已删除策略
        deleted_included = repo.list_all(include_deleted=True)
        assert len(deleted_included) == 2
        deleted_ids = {s.id for s in deleted_included}
        assert s1.id in deleted_ids
        assert s2.id in deleted_ids

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

    def test_save_persists_insufficient_funds_policy(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        strategy = Strategy(name="策略配置", allocated_funds=10000,
                            insufficient_funds_policy="max_buyable")
        saved = repo.save(strategy)
        found = repo.get_by_id(saved.id)
        assert found.insufficient_funds_policy == "max_buyable"

    def test_update_persists_insufficient_funds_policy(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="策略配置", allocated_funds=10000))
        assert saved.insufficient_funds_policy == "reject"
        updated = saved.model_copy(update={"insufficient_funds_policy": "max_buyable"})
        repo.save(updated)
        found = repo.get_by_id(saved.id)
        assert found.insufficient_funds_policy == "max_buyable"

    def test_null_policy_normalized_to_reject(self, db_session):
        """历史数据中 NULL 的 insufficient_funds_policy 应归一为 reject。"""
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="旧数据", allocated_funds=10000))
        row = db_session.get(StrategyModel, saved.id)
        row.insufficient_funds_policy = None
        db_session.commit()
        found = repo.get_by_id(saved.id)
        assert found.insufficient_funds_policy == "reject"

    def test_default_market_price_type_defaults_to_5(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="市价默认", allocated_funds=10000))
        found = repo.get_by_id(saved.id)
        assert found.default_market_price_type == 5

    def test_save_and_update_market_price_type(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="对手方最优", allocated_funds=10000,
                                   default_market_price_type=44))
        found = repo.get_by_id(saved.id)
        assert found.default_market_price_type == 44

    def test_security_type_defaults_to_stock(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="默认券种", allocated_funds=10000))
        found = repo.get_by_id(saved.id)
        assert found.security_type == "stock"

    def test_save_and_update_security_type(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="转债策略", allocated_funds=10000,
                                   security_type="convertible_bond"))
        found = repo.get_by_id(saved.id)
        assert found.security_type == "convertible_bond"
        updated = found.model_copy(update={"security_type": "stock"})
        repo.save(updated)
        assert repo.get_by_id(saved.id).security_type == "stock"

    def test_null_security_type_normalized_to_stock(self, db_session):
        """历史数据中 NULL 的 security_type 应归一为 stock。"""
        repo = SQLAlchemyStrategyRepository(db_session)
        saved = repo.save(Strategy(name="旧数据", allocated_funds=10000))
        row = db_session.get(StrategyModel, saved.id)
        row.security_type = None
        db_session.commit()
        found = repo.get_by_id(saved.id)
        assert found.security_type == "stock"

        updated = saved.model_copy(update={"default_market_price_type": 45})
        repo.save(updated)
        found = repo.get_by_id(saved.id)
        assert found.default_market_price_type == 45


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

    def test_deleted_strategy_not_returned_after_refresh(self, db_session):
        repo = SQLAlchemyStrategyRepository(db_session)
        mgr = StrategyManager(repository=repo)
        strategy = mgr.create(StrategyCreate(name="将被删除", allocated_funds=100000))
        assert mgr.delete(strategy.id) is True

        # 新建一个 StrategyManager 强制从 Repository 刷新缓存
        new_mgr = StrategyManager(repository=repo)
        assert new_mgr.get(strategy.id) is None

        trader = MagicMock()
        trader.query_stock_positions.return_value = []
        account = MagicMock()
        result = new_mgr.list_all_enriched(trader, account)
        assert result == []
