import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from collections import deque
from backend.signal_handler import TradeSignal, SignalReceiver
from backend.qmt_client import create_trader


@pytest.fixture
def signal_log():
    return deque(maxlen=200)


@pytest.fixture
def trader_setup(signal_log):
    trader, account, callback = create_trader("test_account", "/tmp/mock_qmt", signal_log=signal_log)
    return trader, account, callback, signal_log


@pytest.fixture
def receiver(trader_setup):
    trader, account, callback, signal_log = trader_setup
    return SignalReceiver(
        trader=trader,
        account=account,
        callback=callback,
        signal_log=signal_log,
    )


class TestTradeSignal:
    def test_valid_buy_signal(self):
        signal = TradeSignal(
            signal_id="sig-001",
            stock_code="000001.XSHE",
            direction="buy",
            quantity=100,
        )
        assert signal.signal_id == "sig-001"
        assert signal.direction == "buy"
        assert signal.quantity == 100

    def test_valid_sell_signal(self):
        signal = TradeSignal(
            signal_id="sig-002",
            stock_code="600000.XSHG",
            direction="sell",
            quantity=200,
            price=15.50,
        )
        assert signal.price == 15.50
        assert signal.direction == "sell"

    def test_optional_fields_default(self):
        signal = TradeSignal(
            signal_id="sig-003",
            stock_code="000001.XSHE",
            direction="buy",
            quantity=100,
        )
        assert signal.order_type == "limit"
        assert signal.strategy_name is None
        assert signal.timestamp is None

    def test_invalid_direction(self):
        with pytest.raises(ValueError):
            TradeSignal(
                signal_id="sig-004",
                stock_code="000001.XSHE",
                direction="invalid",
                quantity=100,
            )


class TestSignalReceiver:
    @pytest.mark.asyncio
    async def test_receive_buy_signal(self, receiver):
        signal = TradeSignal(
            signal_id="sig-001",
            stock_code="000001.XSHE",
            direction="buy",
            quantity=100,
        )
        result = await receiver.receive_signal(signal)
        assert result["success"] is True
        assert "order_id" in result["data"]
        assert result["data"]["qmt_code"] == "000001.SZ"

    @pytest.mark.asyncio
    async def test_receive_sell_signal(self, receiver):
        signal = TradeSignal(
            signal_id="sig-002",
            stock_code="600000.XSHG",
            direction="sell",
            quantity=200,
            price=15.50,
        )
        result = await receiver.receive_signal(signal)
        assert result["success"] is True
        assert result["data"]["qmt_code"] == "600000.SH"

    @pytest.mark.asyncio
    async def test_signal_added_to_log(self, receiver, signal_log):
        signal = TradeSignal(
            signal_id="sig-003",
            stock_code="000001.XSHE",
            direction="buy",
            quantity=100,
        )
        await receiver.receive_signal(signal)
        assert len(signal_log) > 0
        assert signal_log[-1]["type"] == "signal"
        assert signal_log[-1]["signal_id"] == "sig-003"
        assert signal_log[-1]["status"] == "submitted"
