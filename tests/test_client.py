import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock
from backend.qmt_client import create_trader
from backend.utils import add_stock_suffix, jq_to_qmt, qmt_to_jq


class TestSymbolConversion:
    @pytest.mark.parametrize("jq_code,expected", [
        ("000001.XSHE", "000001.SZ"),
        ("600000.XSHG", "600000.SH"),
        ("430001.XBJ", "430001.BJ"),
        ("000002.XSHE", "000002.SZ"),
    ])
    def test_jq_to_qmt_valid(self, jq_code, expected):
        assert jq_to_qmt(jq_code) == expected

    @pytest.mark.parametrize("jq_code,expected", [
        ("", ""),
        ("000001", "000001"),
        ("000001.XXX", "000001.XXX"),
    ])
    def test_jq_to_qmt_invalid(self, jq_code, expected):
        assert jq_to_qmt(jq_code) == expected

    @pytest.mark.parametrize("qmt_code,expected", [
        ("000001.SZ", "000001.XSHE"),
        ("600000.SH", "600000.XSHG"),
        ("430001.BJ", "430001.XBJ"),
    ])
    def test_qmt_to_jq_valid(self, qmt_code, expected):
        assert qmt_to_jq(qmt_code) == expected


class TestAddStockSuffix:
    def test_sz_stock(self):
        assert add_stock_suffix("000001") == "000001.SZ"
        assert add_stock_suffix("300001") == "300001.SZ"

    def test_sh_stock(self):
        assert add_stock_suffix("600000") == "600000.SH"
        assert add_stock_suffix("688001") == "688001.SH"

    def test_bj_stock(self):
        assert add_stock_suffix("830001") == "830001.BJ"

    def test_sh_convertible_bonds(self):
        assert add_stock_suffix("113665") == "113665.SH"
        assert add_stock_suffix("110043") == "110043.SH"
        assert add_stock_suffix("118003") == "118003.SH"

    def test_sz_convertible_bonds(self):
        assert add_stock_suffix("123001") == "123001.SZ"
        assert add_stock_suffix("127059") == "127059.SZ"
        assert add_stock_suffix("128033") == "128033.SZ"

    def test_exchangeable_bonds(self):
        # 深市可交换债 117 不能被通用 11 前缀误判为沪市
        assert add_stock_suffix("117001") == "117001.SZ"
        # 沪市可交换债 132
        assert add_stock_suffix("132018") == "132018.SH"

    def test_invalid_code(self):
        with pytest.raises(ValueError):
            add_stock_suffix("12345")
        with pytest.raises(ValueError):
            add_stock_suffix("abc123")


class TestCreateTrader:
    def test_create_trader_success(self):
        trader, account, callback = create_trader("test_account", "/tmp/mock_qmt")
        assert trader is not None
        assert account is not None
        assert callback is not None
        assert account.account_id == "test_account"

    def test_create_trader_returns_callback(self):
        trader, account, callback = create_trader("test_account", "/tmp/mock_qmt")
        assert hasattr(callback, 'on_disconnected')
        assert hasattr(callback, 'on_stock_order')
        assert hasattr(callback, 'on_stock_trade')
        assert hasattr(callback, 'on_order_error')
        assert hasattr(callback, 'on_cancel_error')

    def test_mock_trader_exposes_cancel_order_stock(self):
        trader, account, callback = create_trader("test_account", "/tmp/mock_qmt")
        assert hasattr(trader, 'cancel_order_stock')
        result = trader.cancel_order_stock(account, 100001)
        assert result in (0, -1)

    def test_bump_order_counter(self):
        """bump_order_counter 只抬升不回退，避免与历史持久化订单号冲突。"""
        from backend.mock_xtquant import MockTrader
        old_counter = MockTrader._order_counter
        try:
            MockTrader._order_counter = 100000
            trader, _, _ = create_trader("test_account", "/tmp/mock_qmt")
            trader.bump_order_counter(100005)
            assert MockTrader._order_counter == 100005
            trader.bump_order_counter(100003)
            assert MockTrader._order_counter == 100005
        finally:
            MockTrader._order_counter = old_counter


class TestCreateTraderSubscribe:
    def test_subscribe_failure_raises_connection_error(self):
        """win32 环境下 subscribe 返回 -1 应抛 ConnectionError。"""
        mock_trader = MagicMock()
        mock_trader.connect.return_value = 0
        mock_trader.subscribe.return_value = -1

        mock_account = MagicMock()
        mock_account.account_id = "test_account"

        fake_callback_class = MagicMock()
        fake_callback_instance = MagicMock()
        fake_callback_class.return_value = fake_callback_instance

        fake_xtquant = type("Module", (), {})()
        fake_xtquant.XtQuantTrader = MagicMock(return_value=mock_trader)
        fake_xtquant.StockAccount = MagicMock(return_value=mock_account)
        fake_xtquant.XtQuantTraderCallback = fake_callback_class

        fake_xtdata = type("Module", (), {})()

        with patch.dict("sys.modules", {
            "xtquant": type("Module", (), {"xttrader": fake_xtquant, "xttype": fake_xtquant})(),
            "xtquant.xttrader": fake_xtquant,
            "xtquant.xttype": fake_xtquant,
            "xtquant.xtdata": fake_xtdata,
        }):
            with patch("sys.platform", "win32"):
                with pytest.raises(ConnectionError, match="订阅失败"):
                    create_trader("test_account", "/tmp/mock_qmt")
