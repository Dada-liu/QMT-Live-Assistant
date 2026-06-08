import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import pytest
from backend.utils import (
    timestamp_to_datetime_string,
    parse_order_type,
    convert_to_current_date,
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
