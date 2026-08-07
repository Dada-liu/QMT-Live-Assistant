"""挂起买单管理器（调仓资金不足时延迟买入）。

外部策略调仓时"卖 A、买 B"几乎同时到达：卖出只冻结持仓、资金要等卖单
成交后才入账，买单因可用资金不足会被拒。开启策略级开关
`defer_buy_on_insufficient_funds` 后，买单资金不足且存在在途卖单时，
把原始买入请求持久化为挂起买单；订单轮询每轮在卖单对账入账后调用
`process_all` 重试，资金到位即按原始请求语义重新下单（target 类单按
当时持仓重算 delta），超时未成交则过期并通知。
"""
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from backend.bark_notifier import LEVEL_CRITICAL
from backend.db.models.pending_buy_order import (
    PendingBuyOrderModel,
    PENDING_BUY_WAITING,
    PENDING_BUY_SUBMITTED,
    PENDING_BUY_EXPIRED,
    PENDING_BUY_FAILED,
)
from backend.db.repositories.pending_buy import (
    InMemoryPendingBuyRepository,
    PendingBuyRepository,
)
from backend.jukuan_orders import InsufficientFundsError
from backend.logger import logger
from backend.models.order import OrderState
from backend.utils import fetch_stock_names_from_xtdata
from config.settings import settings

# 支持挂起的买入入口方法
_DEFERRABLE_METHODS = (
    "jukuan_order",
    "jukuan_order_target",
    "jukuan_order_value",
    "jukuan_order_target_value",
    "generic_order",
)


class PendingBuyManager:
    """挂起买单的登记、重试与过期清理。"""

    def __init__(
        self,
        strategy_manager,
        order_tracker,
        repository: Optional[PendingBuyRepository] = None,
        signal_log_repository=None,
        bark_service=None,
        handler_factory: Optional[Callable] = None,
        track_callback: Optional[Callable] = None,
    ):
        self._strategy_manager = strategy_manager
        self._order_tracker = order_tracker
        self._repo = repository or InMemoryPendingBuyRepository()
        self._signal_log_repo = signal_log_repository
        self._bark_service = bark_service
        self._handler_factory = handler_factory
        self._track_callback = track_callback

    def has_pending_sell_orders(self, strategy_id: str) -> bool:
        """策略是否存在在途卖单（pending/partial），是挂起买单的前提条件。"""
        return any(
            o.direction == "sell" and o.status in (OrderState.PENDING, OrderState.PARTIAL)
            for o in self._order_tracker.get_orders_by_strategy(strategy_id)
        )

    def defer(
        self,
        strategy_id: str,
        method_name: str,
        stock_code: str,
        payload: dict,
        signal_log_id: Optional[str],
        reason: str,
    ) -> PendingBuyOrderModel:
        """把买入请求登记为挂起买单，等待卖单回款后重试。"""
        now = datetime.now(timezone.utc)
        entity = PendingBuyOrderModel(
            strategy_id=strategy_id,
            method_name=method_name,
            stock_code=stock_code,
            request_payload=dict(payload),
            status=PENDING_BUY_WAITING,
            reason=reason,
            signal_log_id=signal_log_id,
            created_at=now,
            expire_at=now + timedelta(minutes=settings.PENDING_BUY_EXPIRE_MINUTES),
        )
        saved = self._repo.add(entity)
        logger.warning(
            f"【挂起买单】策略 {strategy_id} 买入 {stock_code} 资金不足，"
            f"已挂起等待卖出成交（{settings.PENDING_BUY_EXPIRE_MINUTES} 分钟内有效）: {reason}"
        )
        if self._bark_service is not None:
            self._bark_service.notify_strategy_event(
                strategy_id,
                "买单已挂起",
                f"{stock_code} 买入资金不足，等待卖出成交后自动重试",
            )
        return saved

    def process_all(self, trader=None, account=None):
        """订单轮询每轮调用：先过期清理，再按策略 FIFO 重试 waiting 买单。

        由 server 经 run_blocking 在 poll_and_reconcile（卖单对账入账）之后调用，
        单线程串行执行，无需额外锁。
        """
        now = datetime.now(timezone.utc)
        waiting = self._repo.list_waiting()
        if not waiting:
            return

        for pb in waiting:
            try:
                if pb.expire_at <= now:
                    self._resolve(pb, PENDING_BUY_EXPIRED, "挂起超时，未等到卖出回款")
                    continue
                self._retry(pb)
            except Exception as e:
                # 单个挂起单异常不影响其他单的处理
                logger.error(f"【挂起买单】处理 {pb.id} 异常: {e}")

    # ---- 内部实现 ----

    def _retry(self, pb: PendingBuyOrderModel):
        """重试一笔挂起买单：资金仍不足保持 waiting，成功转正式订单。"""
        strategy = self._strategy_manager.get(pb.strategy_id)
        if strategy is None:
            self._resolve(pb, PENDING_BUY_FAILED, "策略已删除")
            return
        if not strategy.enabled:
            self._resolve(pb, PENDING_BUY_FAILED, "策略已禁用")
            return

        handler = self._handler_factory()
        try:
            result = self._invoke(handler, pb)
        except InsufficientFundsError:
            # 资金仍不足，等下一笔卖单回款
            return

        if result.get("cancelled"):
            # max_buyable 策略仍买不起一手，继续等待
            return

        order_id = result.get("order_id")
        if not order_id:
            self._resolve(pb, PENDING_BUY_FAILED, result.get("message") or "重试未产生订单")
            return

        stock_name = fetch_stock_names_from_xtdata({pb.stock_code}).get(pb.stock_code) or ""
        strategy_name = strategy.name
        result["strategy_name"] = strategy_name
        self._track_callback(result, pb.strategy_id, strategy_name, stock_name=stock_name)
        self._strategy_manager.add_trading_record(pb.strategy_id, {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stock_code": pb.stock_code,
            "direction": result.get("direction", "none"),
            "quantity": result.get("quantity", 0),
            "price": result.get("price", 0),
            "order_id": str(order_id),
            "method": f"{pb.method_name}(deferred)",
        })
        self._resolve(pb, PENDING_BUY_SUBMITTED, None, submitted_order_id=str(order_id))
        logger.info(
            f"【挂起买单成交链路】策略 {pb.strategy_id} 买入 {pb.stock_code} "
            f"已重新下单，订单号 {order_id}"
        )

    def _invoke(self, handler, pb: PendingBuyOrderModel) -> dict:
        """按原始请求语义重建 handler 调用（target 类单按当时持仓重算 delta）。"""
        payload = pb.request_payload
        side = payload.get("side", "long")
        if pb.method_name in ("jukuan_order", "jukuan_order_target"):
            return getattr(handler, pb.method_name)(
                pb.stock_code, payload.get("amount", 0),
                side=side, strategy_id=pb.strategy_id,
            )
        if pb.method_name in ("jukuan_order_value", "jukuan_order_target_value"):
            return getattr(handler, pb.method_name)(
                pb.stock_code, payload.get("value", 0),
                side=side, strategy_id=pb.strategy_id,
            )
        if pb.method_name == "generic_order":
            return handler.generic_order(
                stock_code=pb.stock_code,
                quantity=payload["quantity"],
                direction=payload.get("direction", "buy"),
                price=payload.get("price", 0.0),
                price_type=payload.get("price_type"),
                order_type=payload.get("order_type"),
                strategy_name=payload.get("strategy_name") or "generic_order",
                strategy_id=pb.strategy_id,
                order_remark=payload.get("order_remark"),
            )
        raise ValueError(f"不支持的挂起方法: {pb.method_name}")

    def _resolve(
        self,
        pb: PendingBuyOrderModel,
        status: str,
        reason: Optional[str],
        submitted_order_id: Optional[str] = None,
    ):
        """终态落库 + 信号日志联动 + 通知。"""
        pb.status = status
        pb.resolved_at = datetime.now(timezone.utc)
        if submitted_order_id:
            pb.submitted_order_id = submitted_order_id
        if reason:
            pb.reason = reason
        self._repo.update(pb)

        if self._signal_log_repo is not None and pb.signal_log_id:
            if status == PENDING_BUY_SUBMITTED:
                self._signal_log_repo.update_processed_order(pb.signal_log_id, submitted_order_id)
            else:
                self._signal_log_repo.update_error(pb.signal_log_id, f"挂起买单{status}: {reason}")

        if self._bark_service is not None and status in (PENDING_BUY_EXPIRED, PENDING_BUY_FAILED):
            self._bark_service.notify_strategy_event(
                pb.strategy_id,
                "挂起买单失败" if status == PENDING_BUY_FAILED else "挂起买单已过期",
                f"{pb.stock_code} {reason or ''}".strip(),
                level=LEVEL_CRITICAL,
            )
