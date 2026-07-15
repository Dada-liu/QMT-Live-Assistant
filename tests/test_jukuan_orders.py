import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from backend.jukuan_orders import (
    JukuanOrderHandler, _is_future, _lot_size, _round_down_to_lot,
)
from backend.constants import STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import FIX_PRICE


class TestHelpers:
    def test_is_future_true(self):
        assert _is_future("RB8888.XSGE") is True
        assert _is_future("IF8888.CCFX") is True

    def test_is_future_false(self):
        assert _is_future("000001.SZ") is False
        assert _is_future("600000.SH") is False

    def test_lot_size_stock(self):
        assert _lot_size("000001.SZ") == 100

    def test_lot_size_future(self):
        assert _lot_size("RB8888.XSGE") == 1

    def test_round_down_to_lot_stock(self):
        assert _round_down_to_lot(250, "000001.SZ") == 200
        assert _round_down_to_lot(100, "000001.SZ") == 100
        assert _round_down_to_lot(50, "000001.SZ") == 0

    def test_round_down_to_lot_future(self):
        assert _round_down_to_lot(5, "RB8888.XSGE") == 5
        assert _round_down_to_lot(1, "RB8888.XSGE") == 1


class TestJukuanOrder:
    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_buy(self, handler):
        result = handler.jukuan_order("000001.SZ", 100)
        assert result["direction"] == "buy"
        assert result["quantity"] == 100
        assert result["order_id"] == 200001
        assert result["stock_code"] == "000001.SZ"
        assert result["jq_code"] == "000001.XSHE"
        # 无持仓时从行情获取价格，mock 行情价为 12.55
        assert result["price"] == 12.55
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.55

    def test_sell(self, handler):
        result = handler.jukuan_order("000001.SZ", -100)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100
        assert result["price"] == 12.55
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.55

    def test_zero_quantity_below_lot(self, handler):
        result = handler.jukuan_order("000001.SZ", 50)
        assert result["order_id"] is None
        assert result["direction"] == "none"
        assert result["quantity"] == 0

    def test_future_long(self, handler):
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"RB8888.XSGE": 4500.0}):
            result = handler.jukuan_order("RB8888.XSGE", 3, side="long")
        assert result["direction"] == "buy"
        assert result["quantity"] == 3
        assert result["stock_code"] == "RB8888.XSGE"
        assert result["jq_code"] == "RB8888.XSGE"
        assert result["price"] == 4500.0

    def test_future_short_open(self, handler):
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"RB8888.XSGE": 4500.0}):
            result = handler.jukuan_order("RB8888.XSGE", 3, side="short")
        assert result["direction"] == "sell"
        assert result["price"] == 4500.0

    def test_future_short_cover(self, handler):
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"RB8888.XSGE": 4500.0}):
            result = handler.jukuan_order("RB8888.XSGE", -3, side="short")
        assert result["direction"] == "buy"
        assert result["price"] == 4500.0

    def test_order_error(self, handler):
        handler.trader.order_stock.side_effect = Exception("下单失败")
        with pytest.raises(Exception, match="下单失败"):
            handler.jukuan_order("000001.SZ", 100)


class TestJukuanOrderTarget:
    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001

        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1200.0
        mock_pos.open_price = 12.0
        trader.query_stock_positions.return_value = [mock_pos]

        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_already_at_target(self, handler):
        result = handler.jukuan_order_target("000001.SZ", 100)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert result["order_id"] is None
        assert "目标数量已满足" in result["message"]

    def test_increase(self, handler):
        result = handler.jukuan_order_target("000001.SZ", 200)
        assert result["direction"] == "buy"
        assert result["quantity"] == 100
        assert result["order_id"] == 200001
        # _get_price 使用市值/数量 = 1200/100 = 12.0
        assert result["price"] == 12.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.0

    def test_decrease(self, handler):
        result = handler.jukuan_order_target("000001.SZ", 0)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100
        assert result["price"] == 12.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.0

    def test_delta_below_lot(self, handler):
        handler.trader.query_stock_positions.return_value = []
        result = handler.jukuan_order_target("000001.SZ", 50)
        assert result["direction"] == "none"
        assert result["quantity"] == 0


class TestJukuanOrderValue:
    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001

        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1000.0
        mock_pos.open_price = 10.0
        trader.query_stock_positions.return_value = [mock_pos]

        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_buy_by_value(self, handler):
        result = handler.jukuan_order_value("000001.SZ", 10000)
        assert result["direction"] == "buy"
        assert result["quantity"] == 1000
        assert result["order_id"] == 200001
        assert result["price"] == 10.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.0

    def test_sell_by_value(self, handler):
        result = handler.jukuan_order_value("000001.SZ", -5000)
        assert result["direction"] == "sell"
        assert result["quantity"] == 500
        assert result["price"] == 10.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.0

    def test_value_too_small(self, handler):
        result = handler.jukuan_order_value("000001.SZ", 500)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert result["order_id"] is None
        assert "不足以购买一手" in result["message"]

    def test_no_position_for_price(self, handler):
        handler.trader.query_stock_positions.return_value = []
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={}):
            with pytest.raises(ValueError, match="无法获取"):
                handler.jukuan_order_value("000001.SZ", 10000)

    def test_price_from_market_data_when_no_position(self, handler):
        handler.trader.query_stock_positions.return_value = []
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.jukuan_order_value("000001.SZ", 10000)
        assert result["direction"] == "buy"
        assert result["quantity"] == 700
        assert result["order_id"] == 200001


class TestJukuanOrderTargetValue:
    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001

        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1000.0
        mock_pos.open_price = 10.0
        trader.query_stock_positions.return_value = [mock_pos]

        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_already_at_target_value(self, handler):
        result = handler.jukuan_order_target_value("000001.SZ", 1000)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert "目标价值已满足" in result["message"]

    def test_increase_value(self, handler):
        result = handler.jukuan_order_target_value("000001.SZ", 3000)
        assert result["direction"] == "buy"
        assert result["quantity"] == 200
        assert result["order_id"] == 200001
        assert result["price"] == 10.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.0

    def test_decrease_value(self, handler):
        result = handler.jukuan_order_target_value("000001.SZ", 0)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100
        assert result["price"] == 10.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.0


class TestJukuanOrderStrategyScoped:
    """策略 token 场景下应使用策略级持仓/资金进行计算与校验。"""

    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001

        # 账户持有 100 股，与策略持仓不同
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 100
        mock_pos.market_value = 1000.0
        mock_pos.open_price = 10.0
        trader.query_stock_positions.return_value = [mock_pos]

        account = MagicMock()

        strategy = MagicMock()
        strategy.available_cash = 50000.0
        strategy.positions = [
            {
                "stock_code": "000001.SZ",
                "quantity": 300,
                "available_quantity": 300,
                "frozen_quantity": 0,
                "avg_cost": 12.0,
            }
        ]

        strategy_manager = MagicMock()
        strategy_manager.get.return_value = strategy

        return JukuanOrderHandler(
            trader=trader, account=account, strategy_manager=strategy_manager
        )

    def test_target_uses_strategy_quantity(self, handler):
        result = handler.jukuan_order_target("000001.SZ", 500, strategy_id="strat-1")
        assert result["direction"] == "buy"
        # 策略当前 300，目标 500，缺口 200
        assert result["quantity"] == 200
        # 使用策略持仓 avg_cost=12.0 作为限价
        assert result["price"] == 12.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.0

    def test_target_sell_rejected_when_strategy_short(self, handler):
        # 将策略可用持仓设为 0（全部冻结），此时 target=0 需要卖出 300 股，应被拒绝
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用持仓不足"):
            handler.jukuan_order_target("000001.SZ", 0, strategy_id="strat-1")

    def test_value_buy_capped_by_strategy_cash(self, handler):
        # 策略可用资金 50000，价格 12，最多可买 4100 股（按手数 100 取整）
        result = handler.jukuan_order_value("000001.SZ", 100000, strategy_id="strat-1")
        assert result["direction"] == "buy"
        assert result["quantity"] == 4100
        assert result["price"] == 12.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.0

    def test_value_sell_rejected_when_strategy_short(self, handler):
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用持仓不足"):
            handler.jukuan_order_value("000001.SZ", -100000, strategy_id="strat-1")

    def test_buy_rejected_when_strategy_cash_insufficient(self, handler):
        """固定数量买入超出策略可用资金时应拒绝，并不调用 QMT。"""
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用资金不足"):
            handler.jukuan_order("000001.SZ", 5000, strategy_id="strat-1")
        handler.trader.order_stock.assert_not_called()

    def test_target_buy_rejected_when_strategy_cash_insufficient(self, handler):
        """目标持仓买入超出策略可用资金时应拒绝，并不调用 QMT。"""
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用资金不足"):
            handler.jukuan_order_target("000001.SZ", 1000, strategy_id="strat-1")
        handler.trader.order_stock.assert_not_called()

    def test_buy_rollback_when_qmt_fails(self, handler):
        """QMT 下单失败时应回滚已冻结的策略资金。"""
        snapshot = {"stock_code": "000001.SZ", "delta_cash": -60000.0}
        handler.strategy_manager.apply_optimistic_position.return_value = snapshot
        handler.trader.order_stock.side_effect = Exception("QMT 连接失败")
        with pytest.raises(Exception, match="QMT 连接失败"):
            handler.jukuan_order("000001.SZ", 5000, strategy_id="strat-1")
        handler.strategy_manager.rollback_position.assert_called_once_with("strat-1", snapshot)

    def test_target_value_uses_strategy_current_value(self, handler):
        # 策略当前 300 股 * 12 = 3600，目标 6000，delta=2400，可买 200 股
        result = handler.jukuan_order_target_value("000001.SZ", 6000, strategy_id="strat-1")
        assert result["direction"] == "buy"
        assert result["quantity"] == 200
        assert result["price"] == 12.0
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.0
