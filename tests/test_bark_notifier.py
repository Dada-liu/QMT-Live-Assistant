import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from backend.bark_notifier import (
    BARK_GROUP,
    FAILED_SOUND,
    LEVEL_CRITICAL,
    build_placed_message,
    build_stale_message,
    build_terminal_message,
    build_test_message,
    send_push,
)
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


class TestBuildMessages:
    def test_placed_message(self):
        title, body = build_placed_message(_make_order())
        assert title == "QMT 新订单"
        assert "买入" in body
        assert "平安银行(000001.XSHE)" in body
        assert "100股" in body
        assert "@12.50" in body
        assert "测试策略" in body

    def test_placed_message_market_price(self):
        _, body = build_placed_message(_make_order(price=0.0))
        assert "@市价" in body

    def test_terminal_message_filled(self):
        order = _make_order(status=OrderState.FILLED, filled_quantity=100, filled_price=12.55)
        title, body = build_terminal_message(order)
        assert title == "QMT 订单成交"
        assert "成交:100/100股" in body
        assert "均价:12.55" in body

    def test_terminal_message_failed_with_reason(self):
        order = _make_order(status=OrderState.FAILED, error_msg="资金不足")
        title, body = build_terminal_message(order)
        assert title == "QMT 订单失败"
        assert "原因:资金不足" in body

    def test_terminal_message_failed_without_reason(self):
        order = _make_order(status=OrderState.FAILED, error_msg=None)
        _, body = build_terminal_message(order)
        assert "原因" not in body

    def test_stale_message(self):
        title, body = build_stale_message(_make_order(), 6)
        assert title == "QMT 订单未成交提醒"
        assert "已等待6分钟未成交" in body

    def test_test_message(self):
        title, body = build_test_message()
        assert title == "QMT Live Assistant"
        assert body == "绑定成功"


class TestSendPush:
    @patch("backend.bark_notifier.requests.post")
    def test_posts_payload(self, mock_post):
        mock_post.return_value.raise_for_status = MagicMock()

        ok = send_push("https://api.day.app", "test-key", "标题", "正文")

        assert ok is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.day.app/push"
        assert kwargs["json"]["device_key"] == "test-key"
        assert kwargs["json"]["title"] == "标题"
        assert kwargs["json"]["body"] == "正文"
        assert kwargs["json"]["group"] == BARK_GROUP
        assert kwargs["timeout"] == 10
        # 未传 level/sound 时不应出现在 payload 中
        assert "level" not in kwargs["json"]
        assert "sound" not in kwargs["json"]

    @patch("backend.bark_notifier.requests.post")
    def test_includes_level_and_sound_when_set(self, mock_post):
        mock_post.return_value.raise_for_status = MagicMock()

        send_push("https://api.day.app", "k", "t", "b",
                  level=LEVEL_CRITICAL, sound=FAILED_SOUND)

        payload = mock_post.call_args[1]["json"]
        assert payload["level"] == "critical"
        assert payload["sound"] == "alarm"

    @patch("backend.bark_notifier.requests.post")
    def test_strips_trailing_slash(self, mock_post):
        mock_post.return_value.raise_for_status = MagicMock()

        send_push("https://bark.example.com/", "k", "t", "b")

        assert mock_post.call_args[0][0] == "https://bark.example.com/push"

    @patch("backend.bark_notifier.requests.post")
    def test_empty_server_url_falls_back_to_default(self, mock_post):
        mock_post.return_value.raise_for_status = MagicMock()

        send_push("", "k", "t", "b")

        assert mock_post.call_args[0][0] == "https://api.day.app/push"

    @patch("backend.bark_notifier.requests.post")
    @patch("backend.bark_notifier.logger")
    def test_failure_returns_false_without_raising(self, mock_logger, mock_post):
        mock_post.side_effect = Exception("连接超时")

        ok = send_push("https://api.day.app", "k", "标题", "b")

        assert ok is False
        mock_logger.error.assert_called_once()
        assert "连接超时" in mock_logger.error.call_args[0][0]
