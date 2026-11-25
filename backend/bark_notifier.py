"""Bark 推送通知器（https://api.day.app）。

向 iOS 设备推送订单事件消息。纯发送层：同步 requests 调用，
调用方应负责在后台线程/executor 中执行，避免阻塞订单状态机。
"""
from typing import Optional, Tuple

import requests

from backend.logger import logger
from backend.models.order import OrderState, TrackedOrder

DEFAULT_SERVER_URL = "https://api.day.app"
BARK_GROUP = "QMT订单"
LEVEL_CRITICAL = "critical"
FAILED_SOUND = "alarm"  # Bark 内置铃声，失败订单专用

_TIMEOUT = 10


def send_push(
    server_url: str,
    device_key: str,
    title: str,
    body: str,
    group: str = BARK_GROUP,
    level: Optional[str] = None,
    sound: Optional[str] = None,
) -> bool:
    """同步发送一条 Bark 推送。

    调用方应负责在后台线程/executor 中执行此方法，避免阻塞订单状态机。

    Args:
        server_url: Bark 服务器地址，为空时使用官方 api.day.app。
        device_key: Bark App 中的设备 Key。
        title: 推送标题。
        body: 推送正文。
        group: 消息分组名。
        level: 推送级别，"critical" 时静音/勿扰模式下也会提醒。
        sound: Bark 内置铃声名（如 "alarm"）。

    Returns:
        发送成功返回 True；失败记录日志并返回 False（不抛异常）。
    """
    base = (server_url or DEFAULT_SERVER_URL).rstrip("/")
    payload = {
        "device_key": device_key,
        "title": title,
        "body": body,
        "group": group,
    }
    if level:
        payload["level"] = level
    if sound:
        payload["sound"] = sound
    try:
        response = requests.post(f"{base}/push", json=payload, timeout=_TIMEOUT)
        response.raise_for_status()
        logger.info(f"Bark 推送成功: {title}")
        return True
    except Exception as e:
        logger.error(f"Bark 推送失败: {title}: {e}")
        return False


def _stock_label(order: TrackedOrder) -> str:
    code = order.jq_code or order.stock_code
    return f"{order.stock_name}({code})" if order.stock_name else code


def _direction_label(order: TrackedOrder) -> str:
    return "买入" if order.direction == "buy" else "卖出"


def _price_label(price: float) -> str:
    return f"{price:.2f}" if price > 0 else "市价"


def build_placed_message(order: TrackedOrder) -> Tuple[str, str]:
    """构造"发起订单"推送消息。"""
    title = "QMT 新订单"
    body = (
        f"{_direction_label(order)} {_stock_label(order)} {order.quantity}股"
        f" @{_price_label(order.price)} 策略:{order.strategy_name or '无'}"
    )
    return title, body


def build_terminal_message(order: TrackedOrder) -> Tuple[str, str]:
    """构造终态推送消息：成交或失败（含失败原因）。"""
    if order.status == OrderState.FILLED:
        title = "QMT 订单成交"
        body = (
            f"{_direction_label(order)} {_stock_label(order)}"
            f" 成交:{order.filled_quantity}/{order.quantity}股"
            f" 均价:{order.filled_price:.2f} 策略:{order.strategy_name or '无'}"
        )
    else:
        title = "QMT 订单失败"
        reason = f" 原因:{order.error_msg}" if order.error_msg else ""
        body = (
            f"{_direction_label(order)} {_stock_label(order)} {order.quantity}股"
            f"{reason} 策略:{order.strategy_name or '无'}"
        )
    return title, body


def build_stale_message(order: TrackedOrder, waited_minutes: int) -> Tuple[str, str]:
    """构造"超时未成交"提醒消息。"""
    title = "QMT 订单未成交提醒"
    body = (
        f"{_direction_label(order)} {_stock_label(order)} {order.quantity}股"
        f" @{_price_label(order.price)} 已等待{waited_minutes}分钟未成交"
        f" 策略:{order.strategy_name or '无'}"
    )
    return title, body


def build_test_message() -> Tuple[str, str]:
    """构造绑定验证用的测试消息。"""
    return "QMT Live Assistant", "绑定成功"
