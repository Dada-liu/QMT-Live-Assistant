import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.bark_notifier import FAILED_SOUND, LEVEL_CRITICAL
from backend.bark_service import BARK_SETTINGS_KEY, BarkConfig, BarkService
from backend.db.repositories.settings import InMemorySettingsRepository
from backend.models.order import OrderState, TrackedOrder


def _make_order(**overrides) -> TrackedOrder:
    defaults = dict(
        order_id="100001",
        stock_code="000001.SZ",
        jq_code="000001.XSHE",
        stock_name="平安银行",
        direction="buy",
        quantity=100,
        order_type=23,
        strategy_id="s1",
        strategy_name="测试策略",
        price=12.5,
    )
    defaults.update(overrides)
    return TrackedOrder(**defaults)


def _enabled_service(strategy_lookup=None) -> BarkService:
    service = BarkService(
        InMemorySettingsRepository(), strategy_lookup=strategy_lookup
    )
    service.update_config(BarkConfig(enabled=True, device_key="test-key"))
    return service


class TestGate:
    def test_disabled_by_default(self):
        service = BarkService(InMemorySettingsRepository())
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(_make_order())
        spawn.assert_not_called()

    def test_enabled_without_device_key_blocks(self):
        service = BarkService(InMemorySettingsRepository())
        service.update_config(BarkConfig(enabled=True, device_key=""))
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(_make_order())
        spawn.assert_not_called()

    def test_strategy_toggle_off_blocks(self):
        service = _enabled_service(strategy_lookup=lambda sid: False)
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(_make_order())
        spawn.assert_not_called()

    def test_order_without_strategy_follows_global_only(self):
        lookup_calls = []

        def lookup(strategy_id):
            lookup_calls.append(strategy_id)
            return True

        service = _enabled_service(strategy_lookup=lookup)
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(_make_order(strategy_id=None, strategy_name=""))
        spawn.assert_called_once()

    def test_strategy_lookup_exception_fails_open(self):
        def boom(strategy_id):
            raise RuntimeError("缓存异常")

        service = _enabled_service(strategy_lookup=boom)
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(_make_order())
        spawn.assert_called_once()


class TestNotifyEvents:
    def test_notify_placed_normal_level(self):
        service = _enabled_service()
        order = _make_order()
        with patch.object(service, "_spawn") as spawn:
            service.notify_placed(order)
        spawn.assert_called_once()
        args, kwargs = spawn.call_args
        assert args[0] == "QMT 新订单"
        assert kwargs.get("level") is None
        assert kwargs.get("sound") is None

    def test_notify_terminal_filled_normal_level(self):
        service = _enabled_service()
        order = _make_order(status=OrderState.FILLED, filled_quantity=100, filled_price=12.55)
        with patch.object(service, "_spawn") as spawn:
            service.notify_terminal(order)
        spawn.assert_called_once()
        args, kwargs = spawn.call_args
        assert args[0] == "QMT 订单成交"
        assert kwargs.get("level") is None
        assert kwargs.get("sound") is None

    def test_notify_terminal_failed_critical_with_sound(self):
        service = _enabled_service()
        order = _make_order(status=OrderState.FAILED, error_msg="资金不足")
        with patch.object(service, "_spawn") as spawn:
            service.notify_terminal(order)
        spawn.assert_called_once()
        args, kwargs = spawn.call_args
        assert args[0] == "QMT 订单失败"
        assert kwargs["level"] == LEVEL_CRITICAL
        assert kwargs["sound"] == FAILED_SOUND

    def test_notify_terminal_discards_stale_marker(self):
        service = _enabled_service()
        order = _make_order(status=OrderState.FILLED)
        service._stale_notified.add(order.order_id)
        with patch.object(service, "_spawn"):
            service.notify_terminal(order)
        assert order.order_id not in service._stale_notified


class TestCheckStaleOrders:
    def test_stale_order_notified_once_with_critical(self):
        service = _enabled_service()
        now = datetime.now(timezone.utc)
        order = _make_order(placed_at=now - timedelta(minutes=6))
        with patch.object(service, "_spawn") as spawn:
            service.check_stale_orders([order], now=now)
            service.check_stale_orders([order], now=now + timedelta(seconds=5))
        spawn.assert_called_once()
        args, kwargs = spawn.call_args
        assert args[0] == "QMT 订单未成交提醒"
        assert "已等待6分钟" in args[1]
        assert kwargs["level"] == LEVEL_CRITICAL

    def test_fresh_order_not_notified(self):
        service = _enabled_service()
        now = datetime.now(timezone.utc)
        order = _make_order(placed_at=now - timedelta(minutes=1))
        with patch.object(service, "_spawn") as spawn:
            service.check_stale_orders([order], now=now)
        spawn.assert_not_called()

    def test_naive_placed_at_treated_as_utc(self):
        """DB 读回的 placed_at 无时区信息，应按 UTC 计算年龄。"""
        service = _enabled_service()
        now = datetime.now(timezone.utc)
        naive_placed = (now - timedelta(minutes=6)).replace(tzinfo=None)
        order = _make_order(placed_at=naive_placed)
        with patch.object(service, "_spawn") as spawn:
            service.check_stale_orders([order], now=now)
        spawn.assert_called_once()

    def test_custom_stale_minutes(self):
        service = _enabled_service()
        service.update_config(BarkConfig(enabled=True, device_key="k", stale_minutes=10))
        now = datetime.now(timezone.utc)
        order = _make_order(placed_at=now - timedelta(minutes=6))
        with patch.object(service, "_spawn") as spawn:
            service.check_stale_orders([order], now=now)
        spawn.assert_not_called()

    def test_stale_marker_cleaned_when_order_leaves_pending(self):
        service = _enabled_service()
        now = datetime.now(timezone.utc)
        order = _make_order(placed_at=now - timedelta(minutes=6))
        with patch.object(service, "_spawn"):
            service.check_stale_orders([order], now=now)
        assert order.order_id in service._stale_notified
        service.check_stale_orders([], now=now)
        assert order.order_id not in service._stale_notified

    def test_gate_blocks_stale_notification(self):
        service = _enabled_service(strategy_lookup=lambda sid: False)
        now = datetime.now(timezone.utc)
        order = _make_order(placed_at=now - timedelta(minutes=6))
        with patch.object(service, "_spawn") as spawn:
            service.check_stale_orders([order], now=now)
        spawn.assert_not_called()


class TestConfigPersistence:
    def test_update_config_roundtrip_and_reload(self):
        repo = InMemorySettingsRepository()
        service = BarkService(repo)
        service.update_config(BarkConfig(
            enabled=True, device_key="abc", server_url="https://bark.example.com", stale_minutes=3
        ))
        assert repo.get(BARK_SETTINGS_KEY) is not None

        # 模拟重启：用同一 repo 新建 service，应加载到已保存配置
        reloaded = BarkService(repo)
        config = reloaded.get_config()
        assert config.enabled is True
        assert config.device_key == "abc"
        assert config.server_url == "https://bark.example.com"
        assert config.stale_minutes == 3

    def test_bad_json_falls_back_to_default(self):
        repo = InMemorySettingsRepository()
        repo.set(BARK_SETTINGS_KEY, "{invalid json")
        service = BarkService(repo)
        assert service.get_config() == BarkConfig()


class TestSendTest:
    @patch("backend.bark_service.bark_notifier.send_push", return_value=True)
    def test_send_test_success(self, mock_send):
        service = _enabled_service()
        assert service.send_test() is True
        args, _ = mock_send.call_args
        assert args[1] == "test-key"
        assert args[2] == "QMT Live Assistant"
        assert args[3] == "绑定成功"

    @patch("backend.bark_service.bark_notifier.send_push", return_value=False)
    def test_send_test_failure(self, mock_send):
        service = _enabled_service()
        assert service.send_test() is False

    @patch("backend.bark_service.bark_notifier.send_push")
    def test_send_test_without_device_key(self, mock_send):
        service = BarkService(InMemorySettingsRepository())
        assert service.send_test() is False
        mock_send.assert_not_called()

    @patch("backend.bark_service.bark_notifier.send_push", return_value=True)
    def test_send_test_with_explicit_config(self, mock_send):
        service = BarkService(InMemorySettingsRepository())
        cfg = BarkConfig(enabled=True, device_key="unsaved-key")
        assert service.send_test(cfg) is True
        assert mock_send.call_args[0][1] == "unsaved-key"
