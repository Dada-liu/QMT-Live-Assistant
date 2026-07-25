import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from backend.strategy_manager import (
    Strategy, StrategyCreate, StrategyUpdate, StrategyManager, PositionAssignment,
)


class TestStrategyModel:
    def test_create_minimal(self):
        s = Strategy(name="测试策略")
        assert s.name == "测试策略"
        assert s.description == ""
        assert s.enabled is True
        assert len(s.token) == 32
        assert len(s.id) == 12
        assert s.allocated_funds == 0.0
        assert s.available_cash == 0.0
        assert s.total_asset == 0.0
        assert s.positions == []
        assert s.trading_records == []

    def test_create_full(self):
        s = Strategy(
            name="完整策略",
            description="测试描述",
            allocated_funds=100000.0,
            enabled=False,
        )
        assert s.name == "完整策略"
        assert s.description == "测试描述"
        assert s.allocated_funds == 100000.0
        assert s.enabled is False

    def test_token_unique(self):
        s1 = Strategy(name="A")
        s2 = Strategy(name="B")
        assert s1.token != s2.token
        assert s1.id != s2.id


class TestStrategyCreateModel:
    def test_minimal(self):
        data = StrategyCreate(name="测试", allocated_funds=10000)
        assert data.name == "测试"
        assert data.description == ""
        assert data.allocated_funds == 10000
        assert data.enabled is True
        assert data.positions == []

    def test_full(self):
        data = StrategyCreate(
            name="完整",
            description="描述",
            allocated_funds=50000.0,
            enabled=False,
        )
        assert data.allocated_funds == 50000.0
        assert data.enabled is False

    def test_allocated_funds_required(self):
        with pytest.raises(Exception):
            StrategyCreate(name="测试")

    def test_allocated_funds_must_be_positive(self):
        with pytest.raises(Exception):
            StrategyCreate(name="测试", allocated_funds=0)

    def test_name_must_not_be_empty(self):
        with pytest.raises(Exception):
            StrategyCreate(name="", allocated_funds=10000)


class TestStrategyUpdateModel:
    def test_empty(self):
        data = StrategyUpdate()
        assert data.name is None
        assert data.description is None
        assert data.allocated_funds is None
        assert data.enabled is None

    def test_partial(self):
        data = StrategyUpdate(name="新名称", enabled=False)
        assert data.name == "新名称"
        assert data.enabled is False
        assert data.description is None


class TestInsufficientFundsPolicyConfig:
    """策略可用资金不足时的处理策略配置项。"""

    def test_domain_default_reject(self):
        s = Strategy(name="测试策略")
        assert s.insufficient_funds_policy == "reject"

    def test_create_model_default_reject(self):
        data = StrategyCreate(name="测试", allocated_funds=10000)
        assert data.insufficient_funds_policy == "reject"

    def test_create_model_invalid_policy(self):
        with pytest.raises(Exception):
            StrategyCreate(name="测试", allocated_funds=10000, insufficient_funds_policy="bogus")

    def test_update_model_invalid_policy(self):
        with pytest.raises(Exception):
            StrategyUpdate(insufficient_funds_policy="bogus")

    def test_manager_create_default_reject(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        assert s.insufficient_funds_policy == "reject"
        assert mgr.get(s.id).insufficient_funds_policy == "reject"

    def test_manager_create_with_max_buyable(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(
            name="策略1", allocated_funds=10000, insufficient_funds_policy="max_buyable"
        ))
        assert s.insufficient_funds_policy == "max_buyable"
        assert mgr.get(s.id).insufficient_funds_policy == "max_buyable"

    def test_manager_update_policy(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        updated = mgr.update(s.id, StrategyUpdate(insufficient_funds_policy="max_buyable"))
        assert updated.insufficient_funds_policy == "max_buyable"
        assert mgr.get(s.id).insufficient_funds_policy == "max_buyable"

    def test_manager_update_without_policy_keeps_value(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(
            name="策略1", allocated_funds=10000, insufficient_funds_policy="max_buyable"
        ))
        updated = mgr.update(s.id, StrategyUpdate(name="新名称"))
        assert updated.insufficient_funds_policy == "max_buyable"


class TestStrategyManagerCRUD:
    @pytest.fixture
    def mgr(self):
        return StrategyManager()

    def test_create(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        assert s.name == "策略1"
        assert s.id in mgr._strategies

    def test_get_found(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        found = mgr.get(s.id)
        assert found is not None
        assert found.name == "策略1"

    def test_get_not_found(self, mgr):
        assert mgr.get("nonexistent") is None

    def test_find_by_token(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        found = mgr.find_by_token(s.token)
        assert found is not None
        assert found.id == s.id

    def test_find_by_token_not_found(self, mgr):
        assert mgr.find_by_token("bad-token") is None

    def test_list_all_empty(self, mgr):
        assert mgr.list_all() == []

    def test_list_all_with_strategies(self, mgr):
        mgr.create(StrategyCreate(name="A", allocated_funds=10000))
        mgr.create(StrategyCreate(name="B", allocated_funds=10000))
        result = mgr.list_all()
        assert len(result) == 2
        assert all("id" in d for d in result)

    def test_delete_existing(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        assert mgr.delete(s.id) is True
        assert mgr.get(s.id) is None

    def test_delete_nonexistent(self, mgr):
        assert mgr.delete("nonexistent") is False

    def test_toggle(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000, enabled=True))
        toggled = mgr.toggle(s.id)
        assert toggled.enabled is False
        toggled = mgr.toggle(s.id)
        assert toggled.enabled is True

    def test_toggle_nonexistent(self, mgr):
        assert mgr.toggle("nonexistent") is None

    def test_is_enabled(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000, enabled=True))
        assert mgr.is_enabled(s.id) is True

    def test_is_enabled_disabled(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000, enabled=False))
        assert mgr.is_enabled(s.id) is False

    def test_is_enabled_nonexistent(self, mgr):
        assert mgr.is_enabled("nonexistent") is False


class TestStrategyManagerQueries:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_get_position_found(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        pos = mgr.get_position(sid, "000001.SZ")
        assert pos is not None
        assert pos["quantity"] == 100

    def test_get_position_not_found(self, mgr):
        sid = self._first_id(mgr)
        assert mgr.get_position(sid, "000001.SZ") is None

    def test_get_position_strategy_not_found(self, mgr):
        assert mgr.get_position("nonexistent", "000001.SZ") is None

    def test_get_quantity(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        assert mgr.get_quantity(sid, "000001.SZ") == 100
        assert mgr.get_quantity(sid, "999999.SZ") == 0
        assert mgr.get_quantity("nonexistent", "000001.SZ") == 0

    def test_get_available_quantity(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        assert mgr.get_available_quantity(sid, "000001.SZ") == 100
        assert mgr.get_available_quantity("nonexistent", "000001.SZ") == 0

    def test_get_available_cash(self, mgr):
        sid = self._first_id(mgr)
        assert mgr.get_available_cash(sid) == 100000
        assert mgr.get_available_cash("nonexistent") == 0.0


class TestStrategyManagerUpdate:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="原始", description="原描述", allocated_funds=100000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_update_name(self, mgr):
        s = mgr.update(self._first_id(mgr), StrategyUpdate(name="新名称"))
        assert s.name == "新名称"

    def test_update_description(self, mgr):
        s = mgr.update(self._first_id(mgr), StrategyUpdate(description="新描述"))
        assert s.description == "新描述"

    def test_update_enabled(self, mgr):
        s = mgr.update(self._first_id(mgr), StrategyUpdate(enabled=False))
        assert s.enabled is False

    def test_update_allocated_funds_increase(self, mgr):
        s = mgr.update(self._first_id(mgr), StrategyUpdate(allocated_funds=200000))
        assert s.allocated_funds == 200000
        assert s.available_cash == 200000

    def test_update_allocated_funds_decrease(self, mgr):
        s = mgr.update(self._first_id(mgr), StrategyUpdate(allocated_funds=50000))
        assert s.allocated_funds == 50000
        assert s.available_cash == 50000

    def test_update_nonexistent(self, mgr):
        assert mgr.update("nonexistent", StrategyUpdate(name="X")) is None

    def test_update_updates_timestamp(self, mgr):
        old_ts = mgr.get(self._first_id(mgr)).updated_at
        s = mgr.update(self._first_id(mgr), StrategyUpdate(name="新"))
        assert s.updated_at >= old_ts



class TestStrategyManagerPositions:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_buy_new_position(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        s = mgr.get(sid)
        assert len(s.positions) == 1
        assert s.positions[0]["stock_code"] == "000001.SZ"
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["avg_cost"] == 10.0
        assert s.available_cash == 100000 - 1000

    def test_buy_new_position_fetches_stock_name(self, mgr):
        sid = self._first_id(mgr)
        with patch("backend.strategy_manager.fetch_stock_names_from_xtdata",
                   return_value={"000001.SZ": "平安银行"}):
            mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        s = mgr.get(sid)
        assert len(s.positions) == 1
        pos = s.positions[0]
        assert pos["stock_code"] == "000001.SZ"
        assert pos["stock_name"] == "平安银行"
        assert pos["quantity"] == 100
        assert pos["avg_cost"] == 10.0

    def test_buy_new_position_stock_name_fallback(self, mgr):
        sid = self._first_id(mgr)
        with patch("backend.strategy_manager.fetch_stock_names_from_xtdata",
                   return_value={"000001.SZ": None}):
            mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        s = mgr.get(sid)
        assert len(s.positions) == 1
        assert s.positions[0]["stock_code"] == "000001.SZ"
        assert s.positions[0]["stock_name"] == ""

    def test_buy_add_to_existing(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.update_position(sid, "000001.SZ", "buy", 200, 12.0)
        s = mgr.get(sid)
        assert len(s.positions) == 1
        pos = s.positions[0]
        assert pos["quantity"] == 300
        assert pos["avg_cost"] == round((100 * 10 + 200 * 12) / 300, 4)

    def test_sell_partial(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 300, 10.0)
        mgr.update_position(sid, "000001.SZ", "sell", 100, 12.0)
        s = mgr.get(sid)
        pos = s.positions[0]
        assert pos["quantity"] == 200
        assert s.available_cash == 100000 - 3000 + 1200

    def test_sell_all(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.update_position(sid, "000001.SZ", "sell", 100, 12.0)
        s = mgr.get(sid)
        assert len(s.positions) == 0

    def test_sell_over_quantity(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.update_position(sid, "000001.SZ", "sell", 200, 12.0)
        s = mgr.get(sid)
        assert len(s.positions) == 0

    def test_total_asset_update(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["avg_cost"] == 10.0

    def test_update_nonexistent_strategy(self, mgr):
        mgr.update_position("nonexistent", "000001.SZ", "buy", 100, 10.0)


class TestStrategyManagerOptimisticUpdates:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_apply_optimistic_position_buy(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        s = mgr.get(sid)
        # 买入未成交前不创建 position 行，仅冻结资金
        assert len(s.positions) == 0
        assert s.available_cash == 100000 - 1000
        assert snapshot["quantity"] == 0
        assert snapshot["available_quantity"] == 0
        assert snapshot["frozen_quantity"] == 0
        assert snapshot["available_cash"] == 100000
        assert snapshot["delta_cash"] == -1000
        assert snapshot["delta_frozen_quantity"] == 0

    def test_apply_optimistic_position_buy_insufficient_cash(self, mgr):
        """买入成本超出可用资金时返回 None，且资金不变。"""
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 2000.0)
        assert snapshot is None
        s = mgr.get(sid)
        assert len(s.positions) == 0
        assert s.available_cash == 100000

    def test_apply_optimistic_position_sell(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 300, 10.0)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 300
        assert s.positions[0]["available_quantity"] == 200
        assert s.positions[0]["frozen_quantity"] == 100
        assert s.available_cash == 100000 - 3000
        assert snapshot["quantity"] == 300
        assert snapshot["available_quantity"] == 300
        assert snapshot["frozen_quantity"] == 0
        assert snapshot["avg_cost"] == 10.0
        assert snapshot["delta_cash"] == 0

    def test_rollback_buy_position(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.rollback_position(sid, snapshot)
        s = mgr.get(sid)
        assert len(s.positions) == 0
        assert s.available_cash == 100000

    def test_rollback_sell_position(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 300, 10.0)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)
        mgr.rollback_position(sid, snapshot)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 300
        assert s.positions[0]["avg_cost"] == 10.0
        assert s.available_cash == 100000 - 3000

    def test_sell_pending_does_not_increase_cash(self, mgr):
        """未成交卖出订单只冻结持仓，不增加可用资金。"""
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 300, 10.0)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)

        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 300
        assert s.positions[0]["available_quantity"] == 200
        assert s.positions[0]["frozen_quantity"] == 100
        # 关键：卖出未成交前可用资金不变
        assert s.available_cash == 100000 - 3000
        assert snapshot["delta_cash"] == 0
        assert snapshot["delta_frozen_quantity"] == 100

    def test_reconcile_full_fill(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.reconcile_position(sid, "000001.SZ", "buy", 100, 100, 10.0, snapshot)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["avg_cost"] == 10.0
        assert s.available_cash == 100000 - 1000

    def test_reconcile_full_fill_fetches_stock_name(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        with patch("backend.strategy_manager.fetch_stock_names_from_xtdata",
                   return_value={"000001.SZ": "平安银行"}):
            mgr.reconcile_position(sid, "000001.SZ", "buy", 100, 100, 10.0, snapshot)
        s = mgr.get(sid)
        assert s.positions[0]["stock_code"] == "000001.SZ"
        assert s.positions[0]["stock_name"] == "平安银行"
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["avg_cost"] == 10.0
        assert s.available_cash == 100000 - 1000

    def test_reconcile_partial_buy(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.reconcile_position(sid, "000001.SZ", "buy", 100, 60, 10.2, snapshot)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 60
        assert s.positions[0]["avg_cost"] == 10.2
        assert s.available_cash == 100000 - 60 * 10.2

    def test_reconcile_partial_sell(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 300, 10.0)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)
        mgr.reconcile_position(sid, "000001.SZ", "sell", 100, 60, 12.2, snapshot)
        s = mgr.get(sid)
        assert s.positions[0]["quantity"] == 240
        assert s.positions[0]["avg_cost"] == 10.0
        assert s.available_cash == 100000 - 3000 + 60 * 12.2

    def test_reconcile_zero_fill_rolls_back(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.reconcile_position(sid, "000001.SZ", "buy", 100, 0, 0.0, snapshot)
        s = mgr.get(sid)
        assert len(s.positions) == 0
        assert s.available_cash == 100000


class TestStrategyManagerMultiplePendingOrders:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def _find_pos(self, mgr, stock_code="000001.SZ"):
        s = mgr.get(self._first_id(mgr))
        for p in s.positions:
            if p["stock_code"] == stock_code:
                return p
        return None

    def test_two_buys_pending_no_position_row(self, mgr):
        sid = self._first_id(mgr)
        snapshot_a = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        snapshot_b = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 200, 11.0)

        s = mgr.get(sid)
        # 买入 pending 不创建 position 行，仅累计冻结资金
        assert len(s.positions) == 0
        assert s.available_cash == 100000 - 1000 - 2200

        assert snapshot_a["delta_available_quantity"] == 0
        assert snapshot_a["delta_frozen_quantity"] == 0
        assert snapshot_a["delta_cash"] == -1000

        assert snapshot_b["delta_available_quantity"] == 0
        assert snapshot_b["delta_frozen_quantity"] == 0
        assert snapshot_b["delta_cash"] == -2200

    def test_two_buys_filled_create_position(self, mgr):
        sid = self._first_id(mgr)
        snapshot_a = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        snapshot_b = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 200, 11.0)

        mgr.reconcile_position(sid, "000001.SZ", "buy", 100, 100, 10.5, snapshot_a)

        s = mgr.get(sid)
        pos = s.positions[0]
        assert pos["quantity"] == 100
        assert pos["available_quantity"] == 100
        assert pos["frozen_quantity"] == 0
        assert pos["avg_cost"] == 10.5
        assert s.available_cash == 100000 - 100 * 10.5 - 200 * 11.0

        mgr.reconcile_position(sid, "000001.SZ", "buy", 200, 200, 11.5, snapshot_b)

        s = mgr.get(sid)
        pos = s.positions[0]
        assert pos["quantity"] == 300
        assert pos["available_quantity"] == 300
        assert pos["frozen_quantity"] == 0
        assert pos["avg_cost"] == round((100 * 10.5 + 200 * 11.5) / 300, 4)

    def test_rollback_buy_restores_cash_only(self, mgr):
        sid = self._first_id(mgr)
        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "buy", 100, 10.0)
        mgr.rollback_position(sid, snapshot)

        s = mgr.get(sid)
        assert len(s.positions) == 0
        assert s.available_cash == 100000

    def test_two_sells_interleaved(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 500, 10.0)

        snapshot_a = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)
        snapshot_b = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 200, 13.0)

        pos = self._find_pos(mgr)
        assert pos["quantity"] == 500
        assert pos["available_quantity"] == 200
        assert pos["frozen_quantity"] == 300
        assert mgr.get(sid).available_cash == 100000 - 5000

        mgr.reconcile_position(sid, "000001.SZ", "sell", 100, 100, 12.5, snapshot_a)

        pos = self._find_pos(mgr)
        assert pos["quantity"] == 400
        assert pos["available_quantity"] == 200
        assert pos["frozen_quantity"] == 200
        # 第二个订单仍 pending，不提前增加资金
        assert mgr.get(sid).available_cash == 100000 - 5000 + 100 * 12.5

        mgr.reconcile_position(sid, "000001.SZ", "sell", 200, 200, 13.5, snapshot_b)

        pos = self._find_pos(mgr)
        assert pos["quantity"] == 200
        assert pos["available_quantity"] == 200
        assert pos["frozen_quantity"] == 0
        assert mgr.get(sid).available_cash == 100000 - 5000 + 100 * 12.5 + 200 * 13.5

    def test_rollback_sell_keeps_other_sell_frozen(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 500, 10.0)

        snapshot_a = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 100, 12.0)
        mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 200, 13.0)

        mgr.rollback_position(sid, snapshot_a)

        pos = self._find_pos(mgr)
        assert pos["quantity"] == 500
        assert pos["available_quantity"] == 300
        assert pos["frozen_quantity"] == 200
        assert mgr.get(sid).available_cash == 100000 - 5000

    def test_sell_exceeds_available_rejected(self, mgr):
        sid = self._first_id(mgr)
        mgr.update_position(sid, "000001.SZ", "buy", 100, 10.0)

        snapshot = mgr.apply_optimistic_position(sid, "000001.SZ", "sell", 200, 12.0)
        assert snapshot is None

        pos = self._find_pos(mgr)
        assert pos["quantity"] == 100
        assert pos["available_quantity"] == 100
        assert pos["frozen_quantity"] == 0


class TestStrategyManagerTradingRecords:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_add_record(self, mgr):
        sid = self._first_id(mgr)
        record = {"stock_code": "000001.SZ", "direction": "buy", "quantity": 100}
        mgr.add_trading_record(sid, record)
        s = mgr.get(sid)
        assert len(s.trading_records) == 1
        assert s.trading_records[0]["stock_code"] == "000001.SZ"

    def test_add_record_nonexistent(self, mgr):
        mgr.add_trading_record("nonexistent", {"stock_code": "000001.SZ"})


class TestStrategyManagerDailyProfit:
    def test_default_zero(self):
        mgr = StrategyManager()
        assert mgr.daily_profit == 0.0

    def test_list_all_enriched_empty(self):
        mgr = StrategyManager()
        trader = MagicMock()
        trader.query_stock_positions.return_value = []
        account = MagicMock()
        result = mgr.list_all_enriched(trader, account)
        assert result == []
        assert mgr.daily_profit == 0.0

    def test_list_all_enriched_query_error(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        trader = MagicMock()
        trader.query_stock_positions.side_effect = Exception("查询失败")
        account = MagicMock()
        result = mgr.list_all_enriched(trader, account)
        assert len(result) == 1

    def test_list_all_enriched_with_position_data(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        # 固定交易日，避免触发跨日合并
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(update={"last_rollover_date": "20260712"}))

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260712"):
            result = mgr.list_all_enriched(trader, account)

        d = result[0]
        assert d["positions"][0]["market_value"] == 1200.0
        assert d["positions"][0]["daily_pnl"] == 200.0
        assert d["positions"][0]["current_price"] == 12.0  # 1200 / 100
        assert d["positions"][0]["today_bought_quantity"] == 100
        assert d["positions"][0]["today_bought_cost"] == 1000.0
        assert d["daily_pnl"] == 200.0
        assert mgr.daily_profit == 200.0

    def test_list_all_enriched_today_bought_pnl(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(update={"last_rollover_date": "20260712"}))

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1500.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260712"):
            result = mgr.list_all_enriched(trader, account)

        d = result[0]
        # current_price=15, today_bought_cost=1000, today_qty=100
        assert d["positions"][0]["daily_pnl"] == 500.0
        assert d["daily_pnl"] == 500.0

    def test_list_all_enriched_mixed_yesterday_and_today(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        # 先买入 100 股，并模拟成昨日持仓
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        pos["yesterday_quantity"] = 100
        pos["yesterday_close"] = 10.0
        pos["today_bought_quantity"] = 0
        pos["today_bought_cost"] = 0.0
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(deep=True))
        # 今日再买入 50 股（成交价 12）
        mgr.update_position(s.id, "000001.SZ", "buy", 50, 12.0)
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(update={"last_rollover_date": "20260712"}))

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 150
        mock_pos.market_value = 1950.0  # current_price=13
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260712"):
            result = mgr.list_all_enriched(trader, account)

        d = result[0]
        # yesterday: (13-10)*100 = 300
        # today: 13*50 - 12*50 = 50
        assert d["positions"][0]["daily_pnl"] == 350.0
        assert d["daily_pnl"] == 350.0

    def test_list_all_enriched_no_today_cost_fallback(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        pos["today_bought_cost"] = 0.0  # 模拟缺失成本
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(deep=True))
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(update={"last_rollover_date": "20260712"}))

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260712"):
            result = mgr.list_all_enriched(trader, account)

        d = result[0]
        # today_cost 为 0，今日部分不贡献 daily_pnl
        assert d["positions"][0]["daily_pnl"] == 0.0


class TestStrategyManagerCreateWithPositions:
    @pytest.fixture
    def mgr(self):
        return StrategyManager()

    def test_create_with_positions(self, mgr):
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 12.45, "000002.SZ": 8.10}):
            s = mgr.create(StrategyCreate(
                name="策略1",
                allocated_funds=100000,
                positions=[
                    PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=100, current_price=12.5),
                    PositionAssignment(stock_code="000002.SZ", stock_name="万科A", quantity=200, current_price=8.0),
                ]
            ))
        assert len(s.positions) == 2
        assert s.positions[0]["stock_code"] == "000001.SZ"
        assert s.positions[0]["quantity"] == 100
        assert s.positions[0]["avg_cost"] == 12.45  # xtquant open_price
        assert s.positions[0]["yesterday_quantity"] == 0
        assert s.positions[0]["today_bought_quantity"] == 100
        assert s.positions[0]["today_bought_cost"] == 1245.0
        assert s.positions[1]["stock_code"] == "000002.SZ"
        assert s.positions[1]["quantity"] == 200
        assert s.positions[1]["avg_cost"] == 8.10  # xtquant open_price
        assert s.positions[1]["today_bought_quantity"] == 200
        assert s.positions[1]["today_bought_cost"] == 1620.0
        # 100*12.45 + 200*8.10 = 1245 + 1620 = 2865
        assert s.available_cash == 100000 - 2865

    def test_create_with_positions_exceeds_funds(self, mgr):
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 50.0}):
            with pytest.raises(ValueError, match="超过分配金额"):
                mgr.create(StrategyCreate(
                    name="超额策略",
                    allocated_funds=1000,
                    positions=[
                        PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=100, current_price=50.0),
                    ]
                ))

    def test_create_no_positions(self, mgr):
        s = mgr.create(StrategyCreate(name="空策略", allocated_funds=50000))
        assert len(s.positions) == 0
        assert s.available_cash == 50000
        assert s.total_asset == 50000


class TestStrategyManagerUpdatePositions:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(
            name="原始",
            allocated_funds=100000,
            positions=[
                PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=100, current_price=10.0),
            ]
        ))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_update_replace_positions(self, mgr):
        sid = self._first_id(mgr)
        s = mgr.update(sid, StrategyUpdate(positions=[
            PositionAssignment(stock_code="000002.SZ", stock_name="万科A", quantity=50, current_price=20.0),
        ]))
        assert len(s.positions) == 1
        assert s.positions[0]["stock_code"] == "000002.SZ"
        assert s.positions[0]["quantity"] == 50
        assert s.positions[0]["yesterday_quantity"] == 0
        assert s.positions[0]["today_bought_quantity"] == 50
        assert s.positions[0]["today_bought_cost"] == 50 * s.positions[0]["avg_cost"]

    def test_update_positions_none_unchanged(self, mgr):
        sid = self._first_id(mgr)
        s = mgr.update(sid, StrategyUpdate(name="新名称"))
        assert len(s.positions) == 1
        assert s.name == "新名称"

    def test_update_clear_positions(self, mgr):
        sid = self._first_id(mgr)
        s = mgr.update(sid, StrategyUpdate(positions=[]))
        assert len(s.positions) == 0
        # 移除持仓后退还市场价值
        assert s.available_cash == 100000


class TestStrategyManagerFifoAndRollover:
    def test_sell_fifo_deducts_yesterday_first(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        # 先买入 100 股，并模拟成昨日持仓
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        pos["yesterday_quantity"] = 100
        pos["yesterday_close"] = 10.0
        pos["today_bought_quantity"] = 0
        pos["today_bought_cost"] = 0.0
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(deep=True))
        # 今日再买入 50 股，成交价 12
        mgr.update_position(s.id, "000001.SZ", "buy", 50, 12.0)

        # 卖出 120 股：先扣 100 昨日，再扣 20 今日
        mgr.update_position(s.id, "000001.SZ", "sell", 120, 15.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        assert pos["quantity"] == 30
        assert pos["yesterday_quantity"] == 0
        assert pos["today_bought_quantity"] == 30
        assert pos["today_bought_cost"] == 30 * 12.0
        # 卖出后剩余 30 股全部为今日买入，avg_cost 应更新为今日买入价 12.0
        assert pos["avg_cost"] == 12.0

    def test_sell_partial_yesterday_only(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        pos["yesterday_quantity"] = 100
        pos["yesterday_close"] = 10.0
        pos["today_bought_quantity"] = 0
        pos["today_bought_cost"] = 0.0
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(deep=True))

        mgr.update_position(s.id, "000001.SZ", "sell", 30, 15.0)
        pos = mgr.get_position(s.id, "000001.SZ")
        assert pos["quantity"] == 70
        assert pos["yesterday_quantity"] == 70
        assert pos["today_bought_quantity"] == 0

    def test_rollover_merges_today_into_yesterday(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260713"):
            with patch("backend.strategy_manager.fetch_preclose_from_xtdata",
                       return_value={"000001.SZ": 11.0}):
                result = mgr.list_all_enriched(trader, account)

        s = mgr.get(s.id)
        assert s.last_rollover_date == "20260713"
        pos = s.positions[0]
        assert pos["yesterday_quantity"] == 100
        assert pos["yesterday_close"] == 11.0
        assert pos["today_bought_quantity"] == 0
        assert pos["today_bought_cost"] == 0.0

    def test_rollover_fallback_to_avg_cost_when_preclose_missing(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260713"):
            with patch("backend.strategy_manager.fetch_preclose_from_xtdata",
                       return_value={}):
                mgr.list_all_enriched(trader, account)

        s = mgr.get(s.id)
        assert s.last_rollover_date == "20260713"
        pos = s.positions[0]
        assert pos["yesterday_quantity"] == 100
        assert pos["yesterday_close"] == 10.0  # 回退到 avg_cost
        assert pos["today_bought_quantity"] == 0
        assert pos["today_bought_cost"] == 0.0

    def test_total_pnl_uses_strategy_market_value(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)
        strategy = mgr.get(s.id)
        mgr._persist(strategy.model_copy(update={"last_rollover_date": "20260712"}))

        # QMT 账户总持仓 500 股，市值 6275.0，策略只占 100 股
        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 500
        mock_pos.market_value = 6275.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch.object(mgr, "_current_trade_date", return_value="20260712"):
            result = mgr.list_all_enriched(trader, account)

        d = result[0]
        pos = d["positions"][0]
        # 策略分摊市值 = 6275 * (100/500) = 1255.0
        assert pos["market_value"] == 1255.0
        # total_pnl 必须基于策略自身市值，而不是 QMT 账户总市值 6275.0
        assert pos["total_pnl"] == round(1255.0 - 100 * 10.0, 2)

    def test_rebuild_positions_reduce_updates_avg_cost(self):
        mgr = StrategyManager()
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 10.0}):
            s = mgr.create(StrategyCreate(
                name="策略1",
                allocated_funds=100000,
                positions=[
                    PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=100, current_price=10.0),
                ]
            ))
        # 将持仓更新为更少的数量（减仓），且新价格与旧成本不同
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 20.0}):
            s = mgr.update(s.id, StrategyUpdate(positions=[
                PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=50, current_price=20.0),
            ]))

        pos = s.positions[0]
        assert pos["quantity"] == 50
        # 减仓后 avg_cost 保持原值 10.0
        assert pos["avg_cost"] == 10.0
        # today_bought_cost 必须与 avg_cost * quantity 一致
        assert pos["today_bought_cost"] == round(50 * 10.0, 4)
        assert pos["today_bought_quantity"] == 50

    def test_rebuild_positions_increase_updates_avg_cost(self):
        mgr = StrategyManager()
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 10.0}):
            s = mgr.create(StrategyCreate(
                name="策略1",
                allocated_funds=100000,
                positions=[
                    PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=100, current_price=10.0),
                ]
            ))
        # 增仓：旧 100 股成本 10.0，新增 50 股按开盘价 12.0
        with patch("backend.strategy_manager.fetch_open_prices_from_xtdata",
                   return_value={"000001.SZ": 12.0}):
            s = mgr.update(s.id, StrategyUpdate(positions=[
                PositionAssignment(stock_code="000001.SZ", stock_name="平安银行", quantity=150, current_price=12.0),
            ]))

        pos = s.positions[0]
        assert pos["quantity"] == 150
        # avg_cost = (100*10 + 50*12) / 150 = 10.6667
        expected_avg_cost = round((100 * 10.0 + 50 * 12.0) / 150, 4)
        assert pos["avg_cost"] == expected_avg_cost
        # today_bought_cost 必须与 avg_cost * quantity 一致
        assert pos["today_bought_cost"] == round(150 * expected_avg_cost, 4)
        assert pos["today_bought_quantity"] == 150
