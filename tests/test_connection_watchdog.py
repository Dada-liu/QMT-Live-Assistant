import asyncio
import sys
import os
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.connection_watchdog import QMTConnectionWatchdog, ConnectionState


@pytest.fixture
def watchdog():
    return QMTConnectionWatchdog(
        account_id="test_account",
        qmt_path="/tmp/mock_qmt",
        order_tracker=None,
        health_check_interval=0.2,
        health_check_timeout=0.2,
        max_backoff=1.0,
    )


@pytest.mark.asyncio
async def test_start_connects_and_reports_connected(watchdog):
    await watchdog.start()
    try:
        for _ in range(50):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected
        assert watchdog.state == ConnectionState.CONNECTED.value
        assert watchdog.trader is not None
        assert watchdog.account is not None
        assert watchdog.callback is not None
    finally:
        await watchdog.stop()


@pytest.mark.asyncio
async def test_on_disconnected_triggers_reconnect(watchdog):
    await watchdog.start()
    try:
        for _ in range(50):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected

        watchdog.callback.on_disconnected()
        await asyncio.sleep(0.1)

        for _ in range(100):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected
        assert watchdog.reconnect_attempts == 0
    finally:
        await watchdog.stop()


@pytest.mark.asyncio
async def test_health_check_failure_marks_disconnected(watchdog):
    await watchdog.start()
    try:
        for _ in range(50):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected

        # 模拟持续断连：create_trader 返回的 MockTrader 始终处于断开状态
        from backend.qmt_client import create_trader as original_create_trader

        def create_disconnected_trader(*args, **kwargs):
            trader, account, callback = original_create_trader(*args, **kwargs)
            trader.simulate_disconnect()
            return trader, account, callback

        with patch(
            "backend.connection_watchdog.create_trader",
            side_effect=create_disconnected_trader,
        ):
            watchdog.trader.simulate_disconnect()

            for _ in range(200):
                if watchdog.reconnect_attempts > 0:
                    break
                await asyncio.sleep(0.05)

            assert not watchdog.connected
            assert watchdog.reconnect_attempts >= 1
    finally:
        await watchdog.stop()


@pytest.mark.asyncio
async def test_reconnect_uses_exponential_backoff():
    failing_watchdog = QMTConnectionWatchdog(
        account_id="test_account",
        qmt_path="/tmp/mock_qmt",
        order_tracker=None,
        health_check_interval=0.2,
        max_backoff=0.5,
    )

    call_count = 0

    def fake_create_trader(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("mock failure")

    with patch("backend.connection_watchdog.create_trader", side_effect=fake_create_trader):
        await failing_watchdog.start()
        try:
            for _ in range(200):
                if failing_watchdog.reconnect_attempts >= 3:
                    break
                await asyncio.sleep(0.05)
            assert failing_watchdog.reconnect_attempts >= 3
            assert call_count >= 3
        finally:
            await failing_watchdog.stop()


@pytest.mark.asyncio
async def test_stop_cancels_watchdog_and_disconnected(watchdog):
    await watchdog.start()
    for _ in range(50):
        if watchdog.connected:
            break
        await asyncio.sleep(0.05)
    assert watchdog.connected

    await watchdog.stop()
    assert not watchdog.connected
    assert watchdog.state == ConnectionState.DISCONNECTED.value
    assert watchdog._watchdog_task is None or watchdog._watchdog_task.done()


@pytest.mark.asyncio
async def test_health_check_timeout(watchdog):
    await watchdog.start()
    try:
        for _ in range(50):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)

        original_query = watchdog.trader.query_stock_asset

        def slow_query(account):
            import time
            time.sleep(10)
            return original_query(account)

        watchdog.trader.query_stock_asset = slow_query
        result = await watchdog._health_check()
        assert result is False
    finally:
        await watchdog.stop()


@pytest.mark.asyncio
async def test_no_concurrent_reconnects(watchdog):
    await watchdog.start()
    try:
        for _ in range(50):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected

        for _ in range(20):
            watchdog.callback.on_disconnected()

        await asyncio.sleep(0.1)

        for _ in range(100):
            if watchdog.connected:
                break
            await asyncio.sleep(0.05)
        assert watchdog.connected
        assert watchdog.reconnect_attempts <= 2
    finally:
        await watchdog.stop()


@pytest.mark.asyncio
async def test_connect_timeout_marks_reconnecting_and_retries():
    """create_trader hang 时，watchdog 应在 connect_timeout 后记一次失败
    并进入退避重试，而不是永远停在 CONNECTING。"""
    import time

    timeout_watchdog = QMTConnectionWatchdog(
        account_id="test_account",
        qmt_path="/tmp/mock_qmt",
        order_tracker=None,
        health_check_interval=0.2,
        health_check_timeout=0.2,
        max_backoff=0.5,
        connect_timeout=0.2,
    )

    def hanging_create_trader(*args, **kwargs):
        time.sleep(2)
        raise ConnectionError("hang 之后的迟到失败")

    with patch(
        "backend.connection_watchdog.create_trader",
        side_effect=hanging_create_trader,
    ):
        await timeout_watchdog.start()
        try:
            for _ in range(80):
                if timeout_watchdog.reconnect_attempts >= 1:
                    break
                await asyncio.sleep(0.05)

            assert timeout_watchdog.reconnect_attempts >= 1
            assert "超时" in (timeout_watchdog.last_error or "")
            assert not timeout_watchdog.connected
            # watchdog 未被卡死：仍在重试循环中
            assert timeout_watchdog._watchdog_task is not None
            assert not timeout_watchdog._watchdog_task.done()
        finally:
            await timeout_watchdog.stop()


@pytest.mark.asyncio
async def test_stop_timeout_returns_promptly():
    """trader.stop hang 时，watchdog.stop 应在 stop_timeout 后返回，
    不永久挂起关停流程。"""
    import time

    stop_watchdog = QMTConnectionWatchdog(
        account_id="test_account",
        qmt_path="/tmp/mock_qmt",
        order_tracker=None,
        health_check_interval=0.2,
        health_check_timeout=0.2,
        max_backoff=0.5,
        stop_timeout=0.2,
    )

    await stop_watchdog.start()
    for _ in range(50):
        if stop_watchdog.connected:
            break
        await asyncio.sleep(0.05)
    assert stop_watchdog.connected

    stop_watchdog._trader.stop = lambda: time.sleep(2)

    started = time.monotonic()
    await stop_watchdog.stop()
    elapsed = time.monotonic() - started

    assert elapsed < 1.5
    assert stop_watchdog.state == ConnectionState.DISCONNECTED.value
