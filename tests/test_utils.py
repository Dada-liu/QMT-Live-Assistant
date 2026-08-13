import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import re
import threading
import time
from unittest.mock import patch
import pytest
from backend.utils import (
    timestamp_to_datetime_string,
    parse_order_type,
    convert_to_current_date,
    fetch_latest_prices_from_xtdata,
    normalize_to_qmt,
    seconds_until_market_open,
    qmt_call,
    QMTInteractionError,
    build_server_url,
    is_market_price_type,
    price_type_name,
    validate_price_type_for_market,
    run_blocking,
    is_future,
    is_convertible_bond,
    get_lot_size,
    get_quantity_unit,
    validate_security_type_for_strategy,
    get_tick_size,
    round_price_to_tick,
)
from backend.constants import (
    STOCK_BUY, STOCK_SELL,
    SECURITY_TYPE_STOCK, SECURITY_TYPE_CONVERTIBLE_BOND,
)
from backend.qmt_xtconstant import (
    FIX_PRICE,
    LATEST_PRICE,
    MARKET_SH_CONVERT_5_CANCEL,
    MARKET_SH_CONVERT_5_LIMIT,
    MARKET_PEER_PRICE_FIRST,
    MARKET_MINE_PRICE_FIRST,
    MARKET_SZ_INSTBUSI_RESTCANCEL,
    MARKET_SZ_FULL_OR_CANCEL,
)


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


class TestQmtCall:
    def test_order_stock_success(self):
        class MockTrader:
            def order_stock(self, account, **kwargs):
                return 100001

        result = qmt_call(MockTrader(), "order_stock", "acc")
        assert result == 100001

    def test_order_stock_returns_minus_one_raises(self):
        class MockTrader:
            def order_stock(self, account, **kwargs):
                return -1

        with pytest.raises(QMTInteractionError, match="返回 -1"):
            qmt_call(MockTrader(), "order_stock", "acc")

    def test_cancel_order_stock_returns_minus_one_raises(self):
        class MockTrader:
            def cancel_order_stock(self, account, order_id):
                return -1

        with pytest.raises(QMTInteractionError, match="返回 -1"):
            qmt_call(MockTrader(), "cancel_order_stock", "acc", 100001)

    def test_query_returns_none_raises(self):
        class MockTrader:
            def query_stock_asset(self, account):
                return None

        with pytest.raises(QMTInteractionError, match="返回 None"):
            qmt_call(MockTrader(), "query_stock_asset", "acc")

    def test_query_returns_empty_list_ok(self):
        class MockTrader:
            def query_stock_orders(self, account, cancelable_only=False):
                return []

        result = qmt_call(MockTrader(), "query_stock_orders", "acc", cancelable_only=False)
        assert result == []

    def test_exception_logs_and_raises(self, caplog):
        class MockTrader:
            def order_stock(self, account, **kwargs):
                raise RuntimeError("QMT 崩溃")

        with caplog.at_level("ERROR"):
            with pytest.raises(QMTInteractionError, match="QMT 崩溃"):
                qmt_call(MockTrader(), "order_stock", "acc")

        assert "QMT 调用异常" in caplog.text
        assert "QMT 崩溃" in caplog.text

    def test_context_included_in_log(self, caplog):
        class MockTrader:
            def order_stock(self, account, **kwargs):
                return -1

        with caplog.at_level("ERROR"):
            with pytest.raises(QMTInteractionError):
                qmt_call(
                    MockTrader(),
                    "order_stock",
                    "acc",
                    context={"stock_code": "000001.SZ"},
                )

        assert "000001.SZ" in caplog.text


class TestRunBlocking:
    async def test_returns_result(self):
        def add(a, b):
            return a + b

        result = await run_blocking(add, 1, 2)
        assert result == 3

    async def test_passes_kwargs(self):
        def greet(name, greeting="你好"):
            return f"{greeting}, {name}"

        result = await run_blocking(greet, "QMT", greeting="hello")
        assert result == "hello, QMT"

    async def test_runs_off_event_loop_thread(self):
        def current_thread_name():
            return threading.current_thread().name

        name = await run_blocking(current_thread_name)
        assert name.startswith("blocking-io")

    async def test_underlying_exception_propagates(self):
        def boom():
            raise ValueError("bad")

        with pytest.raises(ValueError, match="bad"):
            await run_blocking(boom)

    async def test_timeout_raises_qmt_interaction_error(self, monkeypatch):
        monkeypatch.setattr("backend.utils.BLOCKING_CALL_TIMEOUT", 0.1)

        def hang():
            time.sleep(2)

        with pytest.raises(QMTInteractionError, match="超时"):
            await run_blocking(hang)

    async def test_explicit_timeout_overrides_default(self):
        def hang():
            time.sleep(2)

        with pytest.raises(QMTInteractionError, match="超时"):
            await run_blocking(hang, timeout=0.1)

    async def test_timeout_does_not_block_event_loop(self, monkeypatch):
        """hang 的调用超时返回后，事件循环上的其他协程不应被拖住。"""
        monkeypatch.setattr("backend.utils.BLOCKING_CALL_TIMEOUT", 0.2)

        async def fast_coro():
            await asyncio.sleep(0.05)
            return "fast"

        started = time.monotonic()
        results = await asyncio.gather(
            run_blocking(lambda: time.sleep(2)),
            fast_coro(),
            return_exceptions=True,
        )
        elapsed = time.monotonic() - started

        assert isinstance(results[0], QMTInteractionError)
        assert results[1] == "fast"
        assert elapsed < 1.5


class TestBuildServerUrl:
    def test_default_root_path(self):
        assert build_server_url("127.0.0.1", 8000) == "http://127.0.0.1:8000"

    def test_specific_host(self):
        assert build_server_url("127.0.0.1", 8000) == "http://127.0.0.1:8000"

    def test_ipv6_wildcard_host(self):
        assert build_server_url("::", 8000) == "http://127.0.0.1:8000"

    def test_root_path_with_leading_slash(self):
        assert build_server_url("127.0.0.1", 8000, "/qmt") == "http://127.0.0.1:8000/qmt"

    def test_root_path_without_leading_slash(self):
        assert build_server_url("127.0.0.1", 8000, "qmt") == "http://127.0.0.1:8000/qmt"

    def test_empty_root_path(self):
        assert build_server_url("127.0.0.1", 8000, "") == "http://127.0.0.1:8000"


class TestIsMarketPriceType:
    def test_market_types(self):
        assert is_market_price_type(LATEST_PRICE) is True
        assert is_market_price_type(MARKET_PEER_PRICE_FIRST) is True
        assert is_market_price_type(MARKET_SZ_FULL_OR_CANCEL) is True

    def test_fix_price_is_not_market(self):
        assert is_market_price_type(FIX_PRICE) is False

    def test_none_is_not_market(self):
        assert is_market_price_type(None) is False


class TestPriceTypeName:
    def test_known_types(self):
        assert price_type_name(LATEST_PRICE) == "最新价"
        assert price_type_name(FIX_PRICE) == "限价"
        assert price_type_name(MARKET_PEER_PRICE_FIRST) == "对手方最优"
        assert price_type_name(MARKET_MINE_PRICE_FIRST) == "本方最优"

    def test_none(self):
        assert price_type_name(None) == "未知"

    def test_unknown_type(self):
        assert price_type_name(999) == "未知类型(999)"


class TestValidatePriceTypeForMarket:
    def test_none_passes(self):
        validate_price_type_for_market("000001.SZ", None)

    def test_unknown_price_type_raises(self):
        with pytest.raises(ValueError, match="不支持的 price_type: 999"):
            validate_price_type_for_market("000001.SZ", 999)

    def test_sh_only_type_rejected_on_sz(self):
        with pytest.raises(ValueError, match="不支持深交所"):
            validate_price_type_for_market("000001.SZ", MARKET_SH_CONVERT_5_CANCEL)

    def test_sz_only_type_rejected_on_sh(self):
        with pytest.raises(ValueError, match="不支持上交所"):
            validate_price_type_for_market("600000.SH", MARKET_SZ_FULL_OR_CANCEL)

    def test_sz_only_type_rejected_on_bj(self):
        with pytest.raises(ValueError, match="不支持北交所"):
            validate_price_type_for_market("830799.BJ", MARKET_SZ_INSTBUSI_RESTCANCEL)

    def test_universal_types_pass_on_all_exchanges(self):
        for code in ("600000.SH", "000001.SZ", "830799.BJ"):
            for price_type in (LATEST_PRICE, FIX_PRICE,
                               MARKET_PEER_PRICE_FIRST, MARKET_MINE_PRICE_FIRST):
                validate_price_type_for_market(code, price_type)

    def test_sh_only_types_pass_on_sh_and_bj(self):
        for code in ("600000.SH", "830799.BJ"):
            validate_price_type_for_market(code, MARKET_SH_CONVERT_5_CANCEL)
            validate_price_type_for_market(code, MARKET_SH_CONVERT_5_LIMIT)

    def test_unrecognized_market_only_set_validated(self):
        # 期货代码无法识别交易所，只做集合校验：合法类型放行
        validate_price_type_for_market("RB8888.XSGE", MARKET_SH_CONVERT_5_CANCEL)
        with pytest.raises(ValueError, match="不支持的 price_type"):
            validate_price_type_for_market("RB8888.XSGE", 999)


class TestIsFuture:
    def test_future_true(self):
        assert is_future("RB8888.XSGE") is True
        assert is_future("IF8888.CCFX") is True

    def test_future_false(self):
        assert is_future("000001.SZ") is False
        assert is_future("600000.SH") is False
        assert is_future("113665.SH") is False


class TestIsConvertibleBond:
    def test_sh_convertible_bonds(self):
        for code in ("110043.SH", "111000.SH", "113665.SH", "118003.SH"):
            assert is_convertible_bond(code) is True

    def test_sz_convertible_bonds(self):
        for code in ("123001.SZ", "127059.SZ", "128033.SZ"):
            assert is_convertible_bond(code) is True

    def test_exchangeable_bonds(self):
        # 可交换债与可转债交易规则一致（10张/手、T+0），一并识别
        assert is_convertible_bond("132018.SH") is True
        assert is_convertible_bond("117001.SZ") is True

    def test_stocks_are_not_bonds(self):
        for code in ("600000.SH", "688981.SH", "000001.SZ", "300750.SZ", "830799.BJ"):
            assert is_convertible_bond(code) is False

    def test_futures_are_not_bonds(self):
        assert is_convertible_bond("RB8888.XSGE") is False

    def test_case_insensitive(self):
        assert is_convertible_bond("113665.sh") is True

    def test_empty_or_suffixless(self):
        assert is_convertible_bond("") is False
        assert is_convertible_bond("113665") is False


class TestGetLotSize:
    def test_stock_lot(self):
        assert get_lot_size("000001.SZ") == 100
        assert get_lot_size("600000.SH") == 100
        assert get_lot_size("830799.BJ") == 100

    def test_convertible_bond_lot(self):
        assert get_lot_size("113665.SH") == 10
        assert get_lot_size("127059.SZ") == 10

    def test_future_lot(self):
        assert get_lot_size("RB8888.XSGE") == 1


class TestGetQuantityUnit:
    def test_bond_unit_zhang(self):
        assert get_quantity_unit("113665.SH") == "张"
        assert get_quantity_unit("127059.SZ") == "张"

    def test_stock_unit_gu(self):
        assert get_quantity_unit("000001.SZ") == "股"
        assert get_quantity_unit("RB8888.XSGE") == "股"


class TestValidateSecurityTypeForStrategy:
    def test_none_security_type_passes(self):
        validate_security_type_for_strategy(None, "113665.SH")
        validate_security_type_for_strategy(None, "000001.SZ")

    def test_stock_strategy_allows_stock(self):
        validate_security_type_for_strategy(SECURITY_TYPE_STOCK, "000001.SZ")
        validate_security_type_for_strategy(SECURITY_TYPE_STOCK, "600000.SH")

    def test_stock_strategy_rejects_bond(self):
        with pytest.raises(ValueError, match="策略种类为股票"):
            validate_security_type_for_strategy(SECURITY_TYPE_STOCK, "113665.SH")
        with pytest.raises(ValueError, match="策略种类为股票"):
            validate_security_type_for_strategy(SECURITY_TYPE_STOCK, "127059.SZ")

    def test_stock_strategy_allows_future(self):
        # 期货代码不受策略券种限制，保持向后兼容
        validate_security_type_for_strategy(SECURITY_TYPE_STOCK, "RB8888.XSGE")

    def test_bond_strategy_allows_bond(self):
        validate_security_type_for_strategy(SECURITY_TYPE_CONVERTIBLE_BOND, "113665.SH")
        validate_security_type_for_strategy(SECURITY_TYPE_CONVERTIBLE_BOND, "127059.SZ")

    def test_bond_strategy_rejects_stock(self):
        with pytest.raises(ValueError, match="策略种类为可转债"):
            validate_security_type_for_strategy(SECURITY_TYPE_CONVERTIBLE_BOND, "000001.SZ")

    def test_bond_strategy_rejects_future(self):
        with pytest.raises(ValueError, match="策略种类为可转债"):
            validate_security_type_for_strategy(SECURITY_TYPE_CONVERTIBLE_BOND, "RB8888.XSGE")


class TestGetTickSize:
    def test_stock_tick(self):
        assert get_tick_size("000001.SZ") == 0.01
        assert get_tick_size("600000.SH") == 0.01
        assert get_tick_size("830799.BJ") == 0.01

    def test_convertible_bond_tick(self):
        assert get_tick_size("113665.SH") == 0.001
        assert get_tick_size("127059.SZ") == 0.001

    def test_future_tick_returns_zero(self):
        # 期货各品种最小变动价位不一（如 IF 0.2），暂不支持对齐，返回 0 表示跳过
        assert get_tick_size("RB8888.XSGE") == 0


class TestRoundPriceToTick:
    def test_stock_rounds_to_two_decimals(self):
        assert round_price_to_tick(10.2366, "000001.SZ") == 10.24
        assert round_price_to_tick(10.2345, "000001.SZ") == 10.23

    def test_stock_half_up(self):
        # ROUND_HALF_UP：10.235 → 10.24（float round 在二进制下结果不可靠，须用 Decimal）
        assert round_price_to_tick(10.235, "600000.SH") == 10.24

    def test_stock_already_aligned_unchanged(self):
        assert round_price_to_tick(10.24, "000001.SZ") == 10.24

    def test_division_price_aligned(self):
        # 模拟 market_value / volume 产生的任意位小数（3071/300 = 10.236666…）
        assert round_price_to_tick(3071 / 300, "000001.SZ") == 10.24

    def test_bond_rounds_to_three_decimals(self):
        assert round_price_to_tick(123.4567, "113665.SH") == 123.457
        assert round_price_to_tick(123.4564, "113665.SH") == 123.456

    def test_bond_keeps_legit_three_decimals(self):
        assert round_price_to_tick(123.456, "127059.SZ") == 123.456

    def test_non_positive_price_unchanged(self):
        assert round_price_to_tick(0.0, "000001.SZ") == 0.0
        assert round_price_to_tick(-1.5, "000001.SZ") == -1.5

    def test_future_price_unchanged(self):
        assert round_price_to_tick(3512.345678, "RB8888.XSGE") == 3512.345678
