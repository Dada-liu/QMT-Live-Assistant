import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from backend.source_platform_notifier import (
    build_payload,
    notify_source_platform,
    resolve_webhook_url,
)


def test_resolve_webhook_url_prefers_order_webhook():
    order = MagicMock()
    order.source_platform_webhook = "http://explicit.example.com"
    order.source_platform = "joinquant"
    assert resolve_webhook_url(order, {"joinquant": "http://mapping.example.com"}) == "http://explicit.example.com"


def test_resolve_webhook_url_falls_back_to_mapping():
    order = MagicMock()
    order.source_platform_webhook = None
    order.source_platform = "joinquant"
    assert resolve_webhook_url(order, {"joinquant": "http://mapping.example.com"}) == "http://mapping.example.com"


def test_resolve_webhook_url_returns_none_when_no_match():
    order = MagicMock()
    order.source_platform_webhook = None
    order.source_platform = "unknown"
    assert resolve_webhook_url(order, {"joinquant": "http://mapping.example.com"}) is None


def test_build_payload_contains_required_fields():
    order = MagicMock()
    order.order_id = "100001"
    order.status = "filled"
    order.source_platform = "joinquant"
    order.strategy_id = "abc"
    order.strategy_name = "测试策略"
    order.stock_code = "000001.SZ"
    order.jq_code = "000001.XSHE"
    order.stock_name = "平安银行"
    order.direction = "buy"
    order.quantity = 100
    order.filled_quantity = 100
    order.filled_price = 12.55
    order.error_msg = None
    order.placed_at.isoformat.return_value = "2026-07-23T10:00:00+00:00"
    order.resolved_at = None

    payload = build_payload(order)
    assert payload["event"] == "order_state_changed"
    assert payload["order_id"] == "100001"
    assert payload["status"] == "filled"
    assert payload["filled_amount"] == 1255.0
    assert payload["source_platform"] == "joinquant"


@patch("backend.source_platform_notifier.requests.post")
def test_notify_source_platform_posts_payload(mock_post):
    order = MagicMock()
    order.order_id = "100001"
    order.source_platform = "joinquant"
    order.status = "filled"
    mock_post.return_value.raise_for_status = MagicMock()

    notify_source_platform(order, "http://test.example.com/webhook")

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://test.example.com/webhook"
    assert kwargs["json"]["order_id"] == "100001"


@patch("backend.source_platform_notifier.requests.post")
@patch("backend.source_platform_notifier.logger")
def test_notify_source_platform_logs_error(mock_logger, mock_post):
    order = MagicMock()
    order.order_id = "100001"
    order.source_platform = "joinquant"
    order.status = "filled"
    mock_post.side_effect = Exception("连接超时")

    notify_source_platform(order, "http://test.example.com/webhook")

    mock_logger.error.assert_called_once()
    assert "连接超时" in mock_logger.error.call_args[0][0]
