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


class TestStrategyManagerCRUD:
    @pytest.fixture
    def mgr(self):
        return StrategyManager()

    def test_create(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        assert s.name == "策略1"
        assert s.id in mgr._strategies
        assert mgr._signal_counts[s.id] == 0

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
        assert all("signal_count" in d for d in result)
        assert result[0]["signal_count"] == 0

    def test_delete_existing(self, mgr):
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        assert mgr.delete(s.id) is True
        assert mgr.get(s.id) is None
        assert mgr._signal_counts.get(s.id) is None

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


class TestStrategyManagerSignals:
    @pytest.fixture
    def mgr(self):
        mgr = StrategyManager()
        mgr.create(StrategyCreate(name="策略1", allocated_funds=10000))
        return mgr

    def _first_id(self, mgr):
        return list(mgr._strategies.keys())[0]

    def test_increment_signal_count(self, mgr):
        sid = self._first_id(mgr)
        mgr.increment_signal_count(sid)
        mgr.increment_signal_count(sid)
        assert mgr.get_signal_count(sid) == 2

    def test_get_signal_count_default(self, mgr):
        assert mgr.get_signal_count("nonexistent") == 0

    def test_signal_count_in_list(self, mgr):
        sid = self._first_id(mgr)
        mgr.increment_signal_count(sid)
        result = mgr.list_all()
        assert result[0]["signal_count"] == 1


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
        assert s.total_asset == s.available_cash + s.positions[0]["market_value"]

    def test_update_nonexistent_strategy(self, mgr):
        mgr.update_position("nonexistent", "000001.SZ", "buy", 100, 10.0)


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

    def test_refresh_from_qmt_empty_positions(self):
        mgr = StrategyManager()
        trader = MagicMock()
        trader.query_stock_positions.return_value = []
        account = MagicMock()
        mgr.refresh_from_qmt(trader, account)
        assert mgr.daily_profit == 0.0

    def test_refresh_from_qmt_query_error(self):
        mgr = StrategyManager()
        trader = MagicMock()
        trader.query_stock_positions.side_effect = Exception("查询失败")
        account = MagicMock()
        mgr.refresh_from_qmt(trader, account)

    def test_refresh_with_position_data(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        mock_pos.open_price = 12.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch("backend.strategy_manager._fetch_preclose_from_xtdata",
                   return_value={"000001.SZ": 10.0}):
            mgr.refresh_from_qmt(trader, account)

        s = mgr.get(s.id)
        assert s.positions[0]["market_value"] == 1200.0
        assert s.positions[0]["daily_pnl"] == 200.0
        assert s.daily_pnl == 200.0
        assert mgr.daily_profit == 200.0

    def test_refresh_no_preclose_from_xtdata(self):
        mgr = StrategyManager()
        s = mgr.create(StrategyCreate(name="策略1", allocated_funds=100000))
        mgr.update_position(s.id, "000001.SZ", "buy", 100, 10.0)

        trader = MagicMock()
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        mock_pos.open_price = 12.0
        trader.query_stock_positions.return_value = [mock_pos]
        account = MagicMock()

        with patch("backend.strategy_manager._fetch_preclose_from_xtdata",
                   return_value={}):
            mgr.refresh_from_qmt(trader, account)

        s = mgr.get(s.id)
        assert s.positions[0]["daily_pnl"] == 0.0
        assert s.daily_pnl == 0.0
        assert mgr.daily_profit == 0.0


class TestStrategyManagerCreateWithPositions:
    @pytest.fixture
    def mgr(self):
        return StrategyManager()

    def test_create_with_positions(self, mgr):
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
        assert s.positions[0]["avg_cost"] == 12.5
        assert s.positions[0]["market_value"] == 1250.0
        assert s.positions[1]["stock_code"] == "000002.SZ"
        assert s.positions[1]["quantity"] == 200
        # 100*12.5 + 200*8.0 = 1250 + 1600 = 2850
        assert s.available_cash == 100000 - 2850
        assert s.total_asset == s.available_cash + 2850

    def test_create_with_positions_exceeds_funds(self, mgr):
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
