import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from backend.jukuan_orders import (
    JukuanOrderHandler, _is_future, _lot_size, _round_down_to_lot,
)
from backend.constants import STOCK_BUY, STOCK_SELL
from backend.qmt_xtconstant import (
    FIX_PRICE,
    LATEST_PRICE,
    MARKET_SH_CONVERT_5_CANCEL,
    MARKET_PEER_PRICE_FIRST,
    MARKET_MINE_PRICE_FIRST,
    MARKET_SZ_INSTBUSI_RESTCANCEL,
)
from backend.utils import QMTInteractionError


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
        # 策略配置为 max_buyable 时，按金额买入按可用资金封顶：
        # 策略可用资金 50000，价格 12，最多可买 4100 股（按手数 100 取整）
        strategy = handler.strategy_manager.get.return_value
        strategy.insufficient_funds_policy = "max_buyable"
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


class TestGenericOrder:
    """JukuanOrderHandler.generic_order 单元测试。"""

    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_buy_with_direction(self, handler):
        result = handler.generic_order("000001.SZ", 100, direction="buy", price=12.55)
        assert result["direction"] == "buy"
        assert result["quantity"] == 100
        assert result["order_id"] == 200001
        assert result["order_type"] == STOCK_BUY
        assert result["price_type"] == FIX_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["order_remark"] == "000001.XSHE"

    def test_sell_with_direction(self, handler):
        result = handler.generic_order("000001.SZ", 100, direction="sell")
        assert result["direction"] == "sell"
        assert result["order_type"] == STOCK_SELL
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_type"] == STOCK_SELL

    def test_buy_with_explicit_order_type(self, handler):
        result = handler.generic_order(
            "000001.SZ", 100, direction="buy", order_type=STOCK_BUY
        )
        assert result["order_type"] == STOCK_BUY

    def test_market_order_price_type(self, handler):
        result = handler.generic_order("000001.SZ", 100, direction="buy", price=0)
        assert result["price_type"] == LATEST_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == LATEST_PRICE
        assert call.kwargs["price"] == 0

    def test_explicit_price_type(self, handler):
        result = handler.generic_order(
            "000001.SZ", 100, direction="buy", price=0, price_type=FIX_PRICE
        )
        assert result["price_type"] == FIX_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 0

    def test_custom_order_remark(self, handler):
        result = handler.generic_order(
            "000001.SZ", 100, direction="buy", order_remark="custom remark"
        )
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_remark"] == "custom remark"

    def test_invalid_direction(self, handler):
        with pytest.raises(ValueError, match="direction 必须为 buy 或 sell"):
            handler.generic_order("000001.SZ", 100, direction="long")

    def test_invalid_order_type(self, handler):
        with pytest.raises(ValueError, match="不支持的 order_type"):
            handler.generic_order("000001.SZ", 100, order_type=999)

    def test_invalid_price_type(self, handler):
        with pytest.raises(ValueError, match="不支持的 price_type"):
            handler.generic_order("000001.SZ", 100, price_type=999)

    def test_stock_buy_quantity_not_lot(self, handler):
        with pytest.raises(ValueError, match="股票买入数量须为100的整数倍"):
            handler.generic_order("000001.SZ", 50, direction="buy")
        handler.trader.order_stock.assert_not_called()

    def test_sell_allows_odd_lot(self, handler):
        result = handler.generic_order("000001.SZ", 50, direction="sell")
        assert result["quantity"] == 50
        assert result["direction"] == "sell"

    def test_future_buy_allows_non_lot(self, handler):
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"RB8888.XSGE": 4500.0}):
            result = handler.generic_order("RB8888.XSGE", 3, direction="buy", price=4500.0)
        assert result["quantity"] == 3
        assert result["price_type"] == FIX_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price"] == 4500.0

    def test_rollback_on_qmt_failure(self, handler):
        snapshot = {"stock_code": "000001.SZ", "delta_cash": -1255.0}
        strategy = MagicMock()
        strategy.available_cash = 50000.0
        strategy.positions = []
        strategy_manager = MagicMock()
        strategy_manager.get.return_value = strategy
        strategy_manager.apply_optimistic_position.return_value = snapshot
        handler.strategy_manager = strategy_manager

        handler.trader.order_stock.side_effect = Exception("QMT 连接失败")
        with pytest.raises(Exception, match="QMT 连接失败"):
            handler.generic_order("000001.SZ", 100, direction="buy", strategy_id="strat-1")
        strategy_manager.rollback_position.assert_called_once_with("strat-1", snapshot)

    def test_rollback_on_order_stock_minus_one(self, handler):
        """order_stock 返回 -1 时应回滚乐观持仓并抛 QMTInteractionError。"""
        snapshot = {"stock_code": "000001.SZ", "delta_cash": -1255.0}
        strategy = MagicMock()
        strategy.available_cash = 50000.0
        strategy.positions = []
        strategy_manager = MagicMock()
        strategy_manager.get.return_value = strategy
        strategy_manager.apply_optimistic_position.return_value = snapshot
        handler.strategy_manager = strategy_manager

        handler.trader.order_stock.return_value = -1
        with pytest.raises(QMTInteractionError, match="返回 -1"):
            handler.generic_order("000001.SZ", 100, direction="buy", strategy_id="strat-1")
        strategy_manager.rollback_position.assert_called_once_with("strat-1", snapshot)

    def test_get_position_info_returns_empty_on_query_failure(self, handler):
        """query_stock_positions 失败时返回空持仓信息。"""
        handler.trader.query_stock_positions.side_effect = RuntimeError("QMT 查询失败")
        from backend.jukuan_orders import _get_position_info
        result = _get_position_info(handler.trader, handler.account, "000001.SZ")
        assert result == {"volume": 0, "price": 0.0, "found": False}


class TestInsufficientFundsPolicy:
    """策略可用资金不足时的处理策略（insufficient_funds_policy）。"""

    @pytest.fixture
    def make_handler(self):
        def _make(policy, available_cash=50000.0):
            trader = MagicMock()
            trader.order_stock.return_value = 200001
            trader.query_stock_positions.return_value = []
            account = MagicMock()

            strategy = MagicMock()
            strategy.available_cash = available_cash
            strategy.insufficient_funds_policy = policy
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
        return _make

    def test_fixed_quantity_buy_capped_under_max_buyable(self, make_handler):
        """max_buyable：固定数量买入超资时按最大可买数量下单。"""
        handler = make_handler("max_buyable")
        # 5000 股 × 12 = 60000 > 50000，封顶为 4100 股
        result = handler.jukuan_order("000001.SZ", 5000, strategy_id="strat-1")
        assert result["order_id"] == 200001
        assert result["quantity"] == 4100
        assert result["direction"] == "buy"
        assert result["requested_quantity"] == 5000
        assert result["funds_cap_note"] is not None
        assert "请求 5000 股" in result["funds_cap_note"]
        assert "实际下单 4100 股" in result["funds_cap_note"]
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 4100
        handler.strategy_manager.apply_optimistic_position.assert_called_once_with(
            "strat-1", "000001.SZ", "buy", 4100, 12.0
        )

    def test_capped_to_zero_returns_cancelled(self, make_handler):
        """max_buyable：可用资金不足一手时返回订单取消，不调用 QMT、不冻结。"""
        handler = make_handler("max_buyable", available_cash=500.0)
        result = handler.jukuan_order("000001.SZ", 100, strategy_id="strat-1")
        assert result["order_id"] is None
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert "订单取消" in result["message"]
        assert result["requested_quantity"] == 100
        assert result["funds_cap_note"] is not None
        assert "订单取消" in result["funds_cap_note"]
        assert "请求 100 股" in result["funds_cap_note"]
        handler.trader.order_stock.assert_not_called()
        handler.strategy_manager.apply_optimistic_position.assert_not_called()

    def test_normal_buy_has_no_funds_cap_note(self, make_handler):
        """max_buyable：未超资的正常下单不带封顶说明。"""
        handler = make_handler("max_buyable")
        result = handler.jukuan_order("000001.SZ", 100, strategy_id="strat-1")
        assert result["order_id"] == 200001
        assert result["quantity"] == 100
        assert result["requested_quantity"] == 100
        assert result["funds_cap_note"] is None

    def test_fixed_quantity_buy_rejected_under_reject(self, make_handler):
        """reject：固定数量买入超资时拒绝下单。"""
        handler = make_handler("reject")
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用资金不足"):
            handler.jukuan_order("000001.SZ", 5000, strategy_id="strat-1")
        handler.trader.order_stock.assert_not_called()

    def test_order_value_capped_under_max_buyable(self, make_handler):
        """max_buyable：按金额买入超资时按最大可买数量下单。"""
        handler = make_handler("max_buyable")
        result = handler.jukuan_order_value("000001.SZ", 100000, strategy_id="strat-1")
        assert result["order_id"] == 200001
        assert result["quantity"] == 4100
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 4100

    def test_order_value_rejected_under_reject(self, make_handler):
        """reject：按金额买入超资时拒绝下单（行为变化：不再静默封顶）。"""
        handler = make_handler("reject")
        handler.strategy_manager.apply_optimistic_position.return_value = None
        with pytest.raises(ValueError, match="策略可用资金不足"):
            handler.jukuan_order_value("000001.SZ", 100000, strategy_id="strat-1")
        handler.trader.order_stock.assert_not_called()

    def test_order_target_capped_under_max_buyable(self, make_handler):
        """max_buyable：目标持仓买入缺口超资时按最大可买数量下单。"""
        handler = make_handler("max_buyable")
        # 策略当前 300 股，目标 5000，缺口 4700 股 × 12 = 56400 > 50000，封顶 4100
        result = handler.jukuan_order_target("000001.SZ", 5000, strategy_id="strat-1")
        assert result["order_id"] == 200001
        assert result["quantity"] == 4100

    def test_market_buy_capped_using_latest_price(self, make_handler):
        """max_buyable：市价买入按最新价估算成本并封顶。"""
        handler = make_handler("max_buyable")
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.0}):
            result = handler.generic_order(
                "000001.SZ", 5000, direction="buy", price=0, strategy_id="strat-1"
            )
        assert result["order_id"] == 200001
        assert result["quantity"] == 4100
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 4100
        assert call.kwargs["price_type"] == LATEST_PRICE

    def test_generic_order_cancelled_when_capped_to_zero(self, make_handler):
        """max_buyable：通用下单封顶为 0 时返回订单取消结果。"""
        handler = make_handler("max_buyable", available_cash=500.0)
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.0}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0, strategy_id="strat-1"
            )
        assert result["order_id"] is None
        assert result["quantity"] == 0
        assert "订单取消" in result["message"]
        handler.trader.order_stock.assert_not_called()

    def test_sell_unaffected_by_max_buyable_policy(self, make_handler):
        """max_buyable 只影响买入，卖出数量保持不变。"""
        handler = make_handler("max_buyable")
        result = handler.jukuan_order("000001.SZ", -300, strategy_id="strat-1")
        assert result["direction"] == "sell"
        assert result["quantity"] == 300
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 300
        handler.strategy_manager.apply_optimistic_position.assert_called_once_with(
            "strat-1", "000001.SZ", "sell", 300, 12.0
        )


class TestStrategyMarketPriceType:
    """策略默认市价下单方式（default_market_price_type）与市价报价类型校验。"""

    @pytest.fixture
    def make_handler(self):
        def _make(default_market_price_type=MARKET_PEER_PRICE_FIRST):
            trader = MagicMock()
            trader.order_stock.return_value = 200001
            account = MagicMock()

            strategy = MagicMock()
            strategy.available_cash = 50000.0
            strategy.positions = []
            strategy.default_market_price_type = default_market_price_type
            strategy_manager = MagicMock()
            strategy_manager.get.return_value = strategy
            strategy_manager.apply_optimistic_position.return_value = {
                "stock_code": "000001.SZ", "delta_cash": -1255.0,
            }

            handler = JukuanOrderHandler(trader=trader, account=account)
            handler.strategy_manager = strategy_manager
            return handler
        return _make

    def test_strategy_default_applied_for_market_order(self, make_handler):
        """price=0 且未显式传 price_type 时，按策略默认的对手方最优(44)下单。"""
        handler = make_handler(MARKET_PEER_PRICE_FIRST)
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0, strategy_id="strat-1"
            )
        assert result["price_type"] == MARKET_PEER_PRICE_FIRST
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == MARKET_PEER_PRICE_FIRST
        assert call.kwargs["price"] == 0

    def test_explicit_price_type_overrides_strategy_default(self, make_handler):
        """显式传 price_type=45 时优先于策略默认的 44。"""
        handler = make_handler(MARKET_PEER_PRICE_FIRST)
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0,
                price_type=MARKET_MINE_PRICE_FIRST, strategy_id="strat-1",
            )
        assert result["price_type"] == MARKET_MINE_PRICE_FIRST
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == MARKET_MINE_PRICE_FIRST
        assert call.kwargs["price"] == 0

    def test_limit_price_unaffected_by_strategy_default(self, make_handler):
        """price>0 时按限价下单，不受策略默认市价方式影响。"""
        handler = make_handler(MARKET_PEER_PRICE_FIRST)
        result = handler.generic_order(
            "000001.SZ", 100, direction="buy", price=12.5, strategy_id="strat-1"
        )
        assert result["price_type"] == FIX_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.5

    def test_strategy_not_found_falls_back_to_latest_price(self, make_handler):
        """策略不存在时回退最新价(5)。"""
        handler = make_handler()
        handler.strategy_manager.get.return_value = None
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0, strategy_id="strat-1"
            )
        assert result["price_type"] == LATEST_PRICE

    def test_invalid_strategy_default_falls_back_to_latest_price(self, make_handler):
        """策略配置了集合之外的值时回退最新价(5)。"""
        handler = make_handler(default_market_price_type=42)
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0, strategy_id="strat-1"
            )
        assert result["price_type"] == LATEST_PRICE

    def test_no_strategy_falls_back_to_latest_price(self):
        """无 strategy_id 时市价单使用最新价(5)。"""
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        handler = JukuanOrderHandler(trader=trader, account=MagicMock())
        result = handler.generic_order("000001.SZ", 100, direction="buy", price=0)
        assert result["price_type"] == LATEST_PRICE

    def test_sh_specific_market_type_on_sh_stock(self, make_handler):
        """上交所股票可用最优五档即时成交剩余撤销(42)，委托价置 0。"""
        handler = make_handler()
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"600000.SH": 10.0}):
            result = handler.generic_order(
                "600000.SH", 100, direction="buy", price=0,
                price_type=MARKET_SH_CONVERT_5_CANCEL, strategy_id="strat-1",
            )
        assert result["price_type"] == MARKET_SH_CONVERT_5_CANCEL
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == MARKET_SH_CONVERT_5_CANCEL
        assert call.kwargs["price"] == 0

    def test_sh_specific_market_type_rejected_on_sz_stock(self, make_handler):
        """深交所股票使用上交所专属报价类型时报中文错误。"""
        handler = make_handler()
        with pytest.raises(ValueError, match="不支持深交所"):
            handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0,
                price_type=MARKET_SH_CONVERT_5_CANCEL, strategy_id="strat-1",
            )
        handler.trader.order_stock.assert_not_called()

    def test_sz_specific_market_type_rejected_on_sh_stock(self, make_handler):
        """上交所股票使用深交所专属报价类型时报中文错误。"""
        handler = make_handler()
        with pytest.raises(ValueError, match="不支持上交所"):
            handler.generic_order(
                "600000.SH", 100, direction="buy", price=0,
                price_type=MARKET_SZ_INSTBUSI_RESTCANCEL, strategy_id="strat-1",
            )
        handler.trader.order_stock.assert_not_called()

    def test_explicit_latest_price_ignores_price(self, make_handler):
        """显式指定最新价(5)时即使带了 price，委托价也置 0。"""
        handler = make_handler()
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.generic_order(
                "000001.SZ", 100, direction="buy", price=12.55,
                price_type=LATEST_PRICE, strategy_id="strat-1",
            )
        assert result["price_type"] == LATEST_PRICE
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == LATEST_PRICE
        assert call.kwargs["price"] == 0

    def test_unknown_price_type_rejected(self, make_handler):
        """集合之外的 price_type 直接拒绝，且不触发资金冻结。"""
        handler = make_handler()
        with pytest.raises(ValueError, match="不支持的 price_type"):
            handler.generic_order(
                "000001.SZ", 100, direction="buy", price=0,
                price_type=999, strategy_id="strat-1",
            )
        handler.trader.order_stock.assert_not_called()
        handler.strategy_manager.apply_optimistic_position.assert_not_called()


class TestConvertibleBondOrders:
    """可转债下单：10 张/手、数量单位为张。"""

    @pytest.fixture
    def make_handler(self):
        def _make(policy="reject", available_cash=50000.0):
            trader = MagicMock()
            trader.order_stock.return_value = 200001
            trader.query_stock_positions.return_value = []
            account = MagicMock()

            strategy = MagicMock()
            strategy.available_cash = available_cash
            strategy.insufficient_funds_policy = policy
            strategy.security_type = "convertible_bond"
            strategy.positions = [
                {
                    "stock_code": "113665.SH",
                    "quantity": 50,
                    "available_quantity": 50,
                    "frozen_quantity": 0,
                    "avg_cost": 126.0,
                }
            ]

            strategy_manager = MagicMock()
            strategy_manager.get.return_value = strategy
            strategy_manager.apply_optimistic_position.return_value = {
                "stock_code": "113665.SH", "delta_cash": -1260.0,
            }
            return JukuanOrderHandler(
                trader=trader, account=account, strategy_manager=strategy_manager
            )
        return _make

    def test_lot_size_bond(self):
        assert _lot_size("113665.SH") == 10
        assert _lot_size("127059.SZ") == 10

    def test_round_down_to_lot_bond(self):
        assert _round_down_to_lot(25, "113665.SH") == 20
        assert _round_down_to_lot(10, "113665.SH") == 10
        assert _round_down_to_lot(5, "113665.SH") == 0

    def test_generic_order_bond_buy_multiple_of_ten_ok(self, make_handler):
        handler = make_handler()
        result = handler.generic_order(
            "113665.SH", 30, direction="buy", price=126.0, strategy_id="strat-1"
        )
        assert result["quantity"] == 30
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 30

    def test_generic_order_bond_buy_not_lot_rejected(self, make_handler):
        handler = make_handler()
        with pytest.raises(ValueError, match="可转债买入数量须为10的整数倍"):
            handler.generic_order(
                "113665.SH", 35, direction="buy", price=126.0, strategy_id="strat-1"
            )
        handler.trader.order_stock.assert_not_called()

    def test_jukuan_order_bond_rounds_to_ten(self, make_handler):
        """聚宽按数量下单：转债数量按 10 张向下取整，消息单位为张。"""
        handler = make_handler()
        result = handler.jukuan_order("113665.SH", 35, strategy_id="strat-1")
        assert result["quantity"] == 30
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 30
        assert "30张" in result["message"]

    def test_max_buyable_cap_rounds_to_ten(self, make_handler):
        """max_buyable：转债按 10 张步长封顶（1300 元 ÷ 126 元/张 = 10 张）。"""
        handler = make_handler(policy="max_buyable", available_cash=1300.0)
        result = handler.jukuan_order("113665.SH", 100, strategy_id="strat-1")
        assert result["quantity"] == 10
        assert result["requested_quantity"] == 100
        assert "张" in result["funds_cap_note"]
        call = handler.trader.order_stock.call_args
        assert call.kwargs["order_volume"] == 10


class TestSecurityTypeEnforcement:
    """策略种类与证券代码券种强校验（_submit_order 集中入口）。"""

    @pytest.fixture
    def make_handler(self):
        def _make(security_type):
            trader = MagicMock()
            trader.order_stock.return_value = 200001
            trader.query_stock_positions.return_value = []
            account = MagicMock()

            strategy = MagicMock()
            strategy.available_cash = 50000.0
            strategy.insufficient_funds_policy = "reject"
            strategy.security_type = security_type
            strategy.positions = []
            strategy_manager = MagicMock()
            strategy_manager.get.return_value = strategy
            strategy_manager.apply_optimistic_position.return_value = {
                "stock_code": "113665.SH", "delta_cash": -1260.0,
            }
            return JukuanOrderHandler(
                trader=trader, account=account, strategy_manager=strategy_manager
            )
        return _make

    def test_bond_strategy_allows_bond_order(self, make_handler):
        handler = make_handler("convertible_bond")
        result = handler.generic_order(
            "113665.SH", 10, direction="buy", price=126.0, strategy_id="strat-1"
        )
        assert result["order_id"] == 200001

    def test_bond_strategy_rejects_stock_order(self, make_handler):
        """可转债策略下股票代码：拒单、不冻结、不调 QMT。"""
        handler = make_handler("convertible_bond")
        with pytest.raises(ValueError, match="策略种类为可转债"):
            handler.generic_order(
                "000001.SZ", 100, direction="buy", price=12.55, strategy_id="strat-1"
            )
        handler.trader.order_stock.assert_not_called()
        handler.strategy_manager.apply_optimistic_position.assert_not_called()

    def test_stock_strategy_rejects_bond_order(self, make_handler):
        handler = make_handler("stock")
        with pytest.raises(ValueError, match="策略种类为股票"):
            handler.generic_order(
                "113665.SH", 10, direction="buy", price=126.0, strategy_id="strat-1"
            )
        handler.trader.order_stock.assert_not_called()

    def test_stock_strategy_allows_stock_order(self, make_handler):
        handler = make_handler("stock")
        result = handler.generic_order(
            "000001.SZ", 100, direction="buy", price=12.55, strategy_id="strat-1"
        )
        assert result["order_id"] == 200001

    def test_no_strategy_skips_security_type_validation(self):
        """无策略（主 Token 链路）不做券种校验。"""
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        handler = JukuanOrderHandler(trader=trader, account=MagicMock())
        result = handler.generic_order("113665.SH", 10, direction="buy", price=126.0)
        assert result["order_id"] == 200001


class TestPriceTickAlignment:
    """_submit_order 汇聚点应将 FIX_PRICE 委托价按 tick 对齐（股票 2 位、可转债 3 位小数）。"""

    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        account = MagicMock()
        return JukuanOrderHandler(trader=trader, account=account)

    def test_sell_price_from_position_value_division_aligned(self, handler):
        # 持仓 300 股、市值 3071 → 参考价 10.236666…，委托价应对齐到 10.24
        mock_pos = MagicMock()
        mock_pos.stock_code = "000001.SZ"
        mock_pos.volume = 300
        mock_pos.market_value = 3071.0
        mock_pos.open_price = 10.0
        handler.trader.query_stock_positions.return_value = [mock_pos]
        result = handler.jukuan_order("000001.SZ", -100)
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.24
        # 返回值中的价格应与实际委托价一致
        assert result["price"] == 10.24

    def test_sell_price_from_strategy_avg_cost_aligned(self):
        # 策略 avg_cost 为 4 位记账小数（10.2345），委托价应对齐到 10.23
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        account = MagicMock()
        strategy = MagicMock()
        strategy.positions = [{
            "stock_code": "000001.SZ", "quantity": 300,
            "available_quantity": 300, "frozen_quantity": 0, "avg_cost": 10.2345,
        }]
        strategy_manager = MagicMock()
        strategy_manager.get.return_value = strategy
        handler = JukuanOrderHandler(
            trader=trader, account=account, strategy_manager=strategy_manager
        )
        result = handler.jukuan_order("000001.SZ", -100, strategy_id="strat-1")
        call = trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 10.23
        assert result["price"] == 10.23

    def test_generic_order_passthrough_price_aligned(self, handler):
        # /api/order 透传的任意精度价格同样对齐
        result = handler.generic_order("000001.SZ", 100, direction="buy", price=12.3456)
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == FIX_PRICE
        assert call.kwargs["price"] == 12.35
        assert result["price"] == 12.35

    def test_bond_price_rounds_to_three_decimals(self, handler):
        result = handler.generic_order("113665.SH", 10, direction="sell", price=123.4567)
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price"] == 123.457
        assert result["price"] == 123.457

    def test_bond_legit_three_decimal_price_kept(self, handler):
        result = handler.generic_order("113665.SH", 10, direction="sell", price=123.456)
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price"] == 123.456

    def test_market_order_price_untouched(self, handler):
        # 市价单不发送价格，price=0 保持原样且报价类型为最新价
        handler.generic_order("000001.SZ", 100, direction="buy", price=0)
        call = handler.trader.order_stock.call_args
        assert call.kwargs["price_type"] == LATEST_PRICE
        assert call.kwargs["price"] == 0
