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
