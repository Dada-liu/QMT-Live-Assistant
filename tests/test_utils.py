import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from unittest.mock import patch
import pytest
from backend.utils import (
    timestamp_to_datetime_string,
    parse_order_type,
    convert_to_current_date,
    fetch_latest_prices_from_xtdata,
    normalize_to_qmt,
    seconds_until_market_open,
)
from backend.constants import STOCK_BUY, STOCK_SELL


class TestTimestampToDatetimeString:
    def test_known_timestamp(self):
        result = timestamp_to_datetime_string(1700000000.0)
        assert re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', result)

    def test_format(self):
        result = timestamp_to_datetime_string(0.0)
        assert re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', result)


class TestParseOrderType:
    def test_buy(self):
        result = parse_order_type(STOCK_BUY)
        assert "买入" in result

    def test_sell(self):
        result = parse_order_type(STOCK_SELL)
        assert "卖出" in result

    def test_unknown(self):
        result = parse_order_type(999)
        assert "未知类型" in result


class TestConvertToCurrentDate:
    def test_converts_date(self):
        result = convert_to_current_date(1700000000.0)
        assert result != 1700000000.0
        assert isinstance(result, float)


class TestFetchLatestPricesFromXtdata:
    def test_empty_codes(self):
        assert fetch_latest_prices_from_xtdata([]) == {}
        assert fetch_latest_prices_from_xtdata(None) == {}

    def test_fetch_known_stock(self):
        result = fetch_latest_prices_from_xtdata(["000001.SZ"])
        assert result == {"000001.SZ": 12.55}

    def test_fetch_multiple_stocks(self):
        result = fetch_latest_prices_from_xtdata(["000001.SZ", "600519.SH"])
        assert result["000001.SZ"] == 12.55
        assert result["600519.SH"] == 1805.0

    def test_unknown_stock_returns_empty(self):
        result = fetch_latest_prices_from_xtdata(["UNKNOWN.SZ"])
        assert result == {}


class TestNormalizeToQmt:
    def test_qmt_code_unchanged(self):
        assert normalize_to_qmt("000001.SZ") == "000001.SZ"
        assert normalize_to_qmt("600000.SH") == "600000.SH"
        assert normalize_to_qmt("430001.BJ") == "430001.BJ"

    def test_jq_code_converted(self):
        assert normalize_to_qmt("000001.XSHE") == "000001.SZ"
        assert normalize_to_qmt("600000.XSHG") == "600000.SH"
        assert normalize_to_qmt("430001.XBJ") == "430001.BJ"

    def test_future_code_unchanged(self):
        assert normalize_to_qmt("RB8888.XSGE") == "RB8888.XSGE"

    def test_empty_code(self):
        assert normalize_to_qmt("") == ""


class TestSecondsUntilMarketOpen:
    def test_before_open_today(self):
        from datetime import datetime, time, timedelta
        # 固定到开盘前 1 小时
        target = datetime.combine(datetime.now().date(), time(9, 30))
        before = target - timedelta(hours=1)
        with patch('backend.utils.datetime') as mock_dt:
            mock_dt.now.return_value = before
            mock_dt.combine = datetime.combine
            result = seconds_until_market_open()
            assert abs(result - 3600.0) < 0.001

    def test_after_open_rolls_to_next_day(self):
        from datetime import datetime, time, timedelta
        target = datetime.combine(datetime.now().date(), time(9, 30))
        after = target + timedelta(hours=1)
        with patch('backend.utils.datetime') as mock_dt:
            mock_dt.now.return_value = after
            mock_dt.combine = datetime.combine
            result = seconds_until_market_open()
            expected = (target + timedelta(days=1) - after).total_seconds()
            assert abs(result - expected) < 0.001

    def test_exactly_at_open(self):
        from datetime import datetime, time
        target = datetime.combine(datetime.now().date(), time(9, 30))
        with patch('backend.utils.datetime') as mock_dt:
            mock_dt.now.return_value = target
            mock_dt.combine = datetime.combine
            result = seconds_until_market_open()
            expected = 24 * 60 * 60
            assert abs(result - expected) < 0.001

    def test_custom_target_time(self):
        from datetime import datetime, time, timedelta
        target = datetime.combine(datetime.now().date(), time(10, 0))
        before = target - timedelta(minutes=30)
        with patch('backend.utils.datetime') as mock_dt:
            mock_dt.now.return_value = before
            mock_dt.combine = datetime.combine
            result = seconds_until_market_open(10, 0)
            assert abs(result - 1800.0) < 0.001
