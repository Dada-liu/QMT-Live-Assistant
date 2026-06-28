import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import MagicMock, patch
from collections import deque
from backend.jukuan_orders import (
    JukuanOrderHandler, _is_future, _lot_size, _round_down_to_lot,
)
from backend.constants import STOCK_BUY, STOCK_SELL


class TestHelpers:
    def test_is_future_true(self):
        assert _is_future("RB8888.XSGE") is True
        assert _is_future("IF8888.CCFX") is True

    def test_is_future_false(self):
        assert _is_future("000001.XSHE") is False
        assert _is_future("600000.XSHG") is False

    def test_lot_size_stock(self):
        assert _lot_size("000001.XSHE") == 100

    def test_lot_size_future(self):
        assert _lot_size("RB8888.XSGE") == 1

    def test_round_down_to_lot_stock(self):
        assert _round_down_to_lot(250, "000001.XSHE") == 200
        assert _round_down_to_lot(100, "000001.XSHE") == 100
        assert _round_down_to_lot(50, "000001.XSHE") == 0

    def test_round_down_to_lot_future(self):
        assert _round_down_to_lot(5, "RB8888.XSGE") == 5
        assert _round_down_to_lot(1, "RB8888.XSGE") == 1


class TestJukuanOrder:
    @pytest.fixture
    def handler(self):
        trader = MagicMock()
        trader.order_stock.return_value = 200001
        account = MagicMock()
        signal_log = deque(maxlen=200)
        return JukuanOrderHandler(trader=trader, account=account, signal_log=signal_log)

    def test_buy(self, handler):
        result = handler.jukuan_order("000001.XSHE", 100)
        assert result["direction"] == "buy"
        assert result["quantity"] == 100
        assert result["order_id"] == 200001

    def test_sell(self, handler):
        result = handler.jukuan_order("000001.XSHE", -100)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100

    def test_zero_quantity_below_lot(self, handler):
        result = handler.jukuan_order("000001.XSHE", 50)
        assert result["order_id"] is None
        assert result["direction"] == "none"
        assert result["quantity"] == 0

    def test_future_long(self, handler):
        result = handler.jukuan_order("RB8888.XSGE", 3, side="long")
        assert result["direction"] == "buy"
        assert result["quantity"] == 3

    def test_future_short_open(self, handler):
        result = handler.jukuan_order("RB8888.XSGE", 3, side="short")
        assert result["direction"] == "sell"

    def test_future_short_cover(self, handler):
        result = handler.jukuan_order("RB8888.XSGE", -3, side="short")
        assert result["direction"] == "buy"

    def test_signal_logged(self, handler):
        handler.jukuan_order("000001.XSHE", 100)
        assert len(handler.signal_log) == 1
        entry = handler.signal_log[-1]
        assert entry["type"] == "jukuan_order"
        assert entry["stock_code"] == "000001.XSHE"
        assert entry["status"] == "submitted"

    def test_order_error(self, handler):
        handler.trader.order_stock.side_effect = Exception("下单失败")
        with pytest.raises(Exception, match="下单失败"):
            handler.jukuan_order("000001.XSHE", 100)
        assert handler.signal_log[-1]["status"] == "failed"


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
        signal_log = deque(maxlen=200)
        return JukuanOrderHandler(trader=trader, account=account, signal_log=signal_log)

    def test_already_at_target(self, handler):
        result = handler.jukuan_order_target("000001.XSHE", 100)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert result["order_id"] is None
        assert "目标数量已满足" in result["message"]

    def test_increase(self, handler):
        result = handler.jukuan_order_target("000001.XSHE", 200)
        assert result["direction"] == "buy"
        assert result["quantity"] == 100
        assert result["order_id"] == 200001

    def test_decrease(self, handler):
        result = handler.jukuan_order_target("000001.XSHE", 0)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100

    def test_delta_below_lot(self, handler):
        handler.trader.query_stock_positions.return_value = []
        result = handler.jukuan_order_target("000001.XSHE", 50)
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
        signal_log = deque(maxlen=200)
        return JukuanOrderHandler(trader=trader, account=account, signal_log=signal_log)

    def test_buy_by_value(self, handler):
        result = handler.jukuan_order_value("000001.XSHE", 10000)
        assert result["direction"] == "buy"
        assert result["quantity"] == 1000
        assert result["order_id"] == 200001

    def test_sell_by_value(self, handler):
        result = handler.jukuan_order_value("000001.XSHE", -5000)
        assert result["direction"] == "sell"
        assert result["quantity"] == 500

    def test_value_too_small(self, handler):
        result = handler.jukuan_order_value("000001.XSHE", 500)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert result["order_id"] is None
        assert "不足以购买一手" in result["message"]

    def test_no_position_for_price(self, handler):
        handler.trader.query_stock_positions.return_value = []
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={}):
            with pytest.raises(ValueError, match="无法获取"):
                handler.jukuan_order_value("000001.XSHE", 10000)

    def test_price_from_market_data_when_no_position(self, handler):
        handler.trader.query_stock_positions.return_value = []
        with patch("backend.jukuan_orders.fetch_latest_prices_from_xtdata",
                   return_value={"000001.SZ": 12.55}):
            result = handler.jukuan_order_value("000001.XSHE", 10000)
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
        signal_log = deque(maxlen=200)
        return JukuanOrderHandler(trader=trader, account=account, signal_log=signal_log)

    def test_already_at_target_value(self, handler):
        result = handler.jukuan_order_target_value("000001.XSHE", 1000)
        assert result["direction"] == "none"
        assert result["quantity"] == 0
        assert "目标价值已满足" in result["message"]

    def test_increase_value(self, handler):
        result = handler.jukuan_order_target_value("000001.XSHE", 3000)
        assert result["direction"] == "buy"
        assert result["quantity"] == 200
        assert result["order_id"] == 200001

    def test_decrease_value(self, handler):
        result = handler.jukuan_order_target_value("000001.XSHE", 0)
        assert result["direction"] == "sell"
        assert result["quantity"] == 100
