import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch
from backend.qmt_client import jq_to_qmt, qmt_to_jq, create_trader
from backend.utils import add_stock_suffix


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
