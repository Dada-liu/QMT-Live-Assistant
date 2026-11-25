"""源平台订单状态通知器。

当订单到达终态（成交/失败）且调用方要求通知时，向源平台（聚宽、果仁等）
发送结构化的订单状态 POST 回调。
"""
from datetime import datetime, timezone
from typing import Optional

import requests

from backend.logger import logger
from backend.models.order import TrackedOrder


def resolve_webhook_url(order: TrackedOrder, mapping: dict) -> Optional[str]:
    """解析订单对应的源平台 webhook 地址。

    优先使用订单上显式指定的 source_platform_webhook；若未指定，
    则根据 source_platform 从全局映射表中查找。

    Args:
        order: 被跟踪的订单对象。
        mapping: source_platform 到 webhook URL 的全局映射字典。

    Returns:
        解析到的 webhook URL；未找到时返回 None。
    """
    if order.source_platform_webhook:
        return order.source_platform_webhook
    if order.source_platform:
        return mapping.get(order.source_platform)
    return None


def build_payload(order: TrackedOrder) -> dict:
    """构造发送给源平台的订单状态 payload。"""
    return {
        "event": "order_state_changed",
        "order_id": order.order_id,
        "status": order.status,
        "source_platform": order.source_platform,
        "strategy_id": order.strategy_id,
        "strategy_name": order.strategy_name,
        "stock_code": order.stock_code,
        "jq_code": order.jq_code,
        "stock_name": order.stock_name,
        "direction": order.direction,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "filled_price": order.filled_price,
        "filled_amount": round(order.filled_quantity * order.filled_price, 4),
        "error_msg": order.error_msg,
        "placed_at": order.placed_at.isoformat() if order.placed_at else None,
        "resolved_at": order.resolved_at.isoformat() if order.resolved_at else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def notify_source_platform(order: TrackedOrder, webhook_url: str) -> None:
    """同步向源平台 webhook 发送订单状态通知。

    调用方应负责在后台线程/executor 中执行此方法，避免阻塞订单状态机。

    Args:
        order: 已到达终态的订单对象。
        webhook_url: 源平台回调地址。
    """
    payload = build_payload(order)
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(
            f"已通知源平台 {order.source_platform} 订单 {order.order_id} 状态 {order.status}"
        )
    except Exception as e:
        logger.error(
            f"通知源平台失败 {order.source_platform} 订单 {order.order_id}: {e}"
        )
