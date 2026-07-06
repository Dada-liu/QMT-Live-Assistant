"""订单生命周期跟踪器。

维护订单状态机，接收 xtquant 回调与主动查询结果，
在订单到达终端状态（已成交/已失败）时通知订阅者进行策略持仓修正。
"""
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from backend.qmt_xtconstant import (
    ORDER_CANCELED,
    ORDER_JUNK,
    ORDER_PART_CANCEL,
    ORDER_PART_SUCC,
    ORDER_SUCCEEDED,
)
from backend.logger import logger
from backend.constants import GREEN, YELLOW, BLUE, RESET
from backend.db.repositories.order import OrderRepository, InMemoryOrderRepository
from backend.models.order import TrackedOrder, OrderState


class OrderTracker:
    """跟踪订单从下单到终态的完整生命周期。"""

    def __init__(self, repository: Optional[OrderRepository] = None):
        self._repo = repository or InMemoryOrderRepository()
        self._orders: Dict[str, TrackedOrder] = {}
        self._state_change_callbacks: List[Callable[[TrackedOrder], None]] = []
        self.on_state_change(self._log_state_change)
        self._load_orders()

    def on_state_change(self, callback: Callable[[TrackedOrder], None]):
        """注册订单状态到达终态时的回调。"""
        self._state_change_callbacks.append(callback)

    def _log_state_change(self, order: TrackedOrder):
        """统一记录订单状态变化日志。"""
        code = order.jq_code or order.stock_code
        direction_text = '买入' if order.direction == 'buy' else '卖出'
        if order.status == OrderState.FILLED:
            logger.info(
                f"{GREEN}【订单成交】{RESET} "
                f"订单ID:{order.order_id} 股票:{code} 方向:{direction_text} "
                f"委托:{order.quantity} 成交:{order.filled_quantity} "
                f"成交均价:{order.filled_price:.2f} 策略:{order.strategy_name or '无'}"
            )
        elif order.status == OrderState.FAILED:
            error_detail = f" 原因:{order.error_msg}" if order.error_msg else ""
            logger.warning(
                f"{YELLOW}【订单失败】{RESET} "
                f"订单ID:{order.order_id} 股票:{code} 方向:{direction_text} "
                f"委托:{order.quantity}{error_detail} 策略:{order.strategy_name or '无'}"
            )

    def track_order(
        self,
        order_id: Any,
        stock_code: str,
        jq_code: str,
        direction: str,
        quantity: int,
        order_type: int,
        strategy_id: Optional[str],
        strategy_name: str,
        price: float,
        optimistic_position_applied: bool = False,
    ) -> TrackedOrder:
        """注册一笔新订单。"""
        order = TrackedOrder(
            order_id=str(order_id),
            stock_code=stock_code,
            jq_code=jq_code,
            direction=direction,
            quantity=quantity,
            order_type=order_type,
            strategy_id=str(strategy_id) if strategy_id else None,
            strategy_name=str(strategy_name) if strategy_name else "",
            price=price,
            optimistic_position_applied=optimistic_position_applied,
        )
        self._orders[order.order_id] = order
        self._repo.save(order)
        self._record_event(order, "placed", None, "manual")
        logger.info(
            f"{BLUE}【新订单】{RESET} "
            f"订单ID:{order.order_id} 股票:{jq_code or stock_code} "
            f"方向:{'买入' if direction == 'buy' else '卖出'} 数量:{quantity} "
            f"价格:{price if price > 0 else '市价'} 策略:{strategy_name or '无'}"
        )
        return order

    def update_from_callback(
        self,
        order_id: Any,
        xtquant_status: Optional[int],
        traded_volume: int = 0,
        traded_price: float = 0.0,
    ) -> Optional[TrackedOrder]:
        """处理 xtquant on_stock_order 回调。"""
        order = self._orders.get(str(order_id))
        if not order:
            return None

        old_status = order.status
        order.xtquant_status = xtquant_status
        new_status = self._normalize_status(xtquant_status)

        if traded_volume > 0:
            order.filled_quantity, order.filled_price = self._compute_fill(
                order, traded_volume, traded_price
            )

        if new_status == OrderState.FILLED:
            self._resolve(order, OrderState.FILLED, old_status, "callback")
        elif new_status == OrderState.PARTIAL:
            order.status = OrderState.PARTIAL
            self._persist(order, old_status, "callback")
            logger.info(
                f"{BLUE}【部分成交】{RESET} "
                f"订单ID:{order.order_id} 股票:{order.jq_code or order.stock_code} "
                f"成交:{order.filled_quantity}/{order.quantity} "
                f"成交均价:{order.filled_price:.2f}"
            )
        elif new_status == OrderState.FAILED:
            if order.filled_quantity > 0:
                self._resolve(order, OrderState.FILLED, old_status, "callback")
            else:
                self._resolve(order, OrderState.FAILED, old_status, "callback")
        else:
            self._persist(order, old_status, "callback")

        return order

    def update_from_trade(
        self,
        order_id: Any,
        traded_volume: int,
        traded_price: float,
    ) -> Optional[TrackedOrder]:
        """处理 xtquant on_stock_trade 成交回调。"""
        order = self._orders.get(str(order_id))
        if not order:
            return None

        old_status = order.status
        order.filled_quantity, order.filled_price = self._compute_fill(
            order, traded_volume, traded_price
        )

        if order.filled_quantity >= order.quantity:
            self._resolve(order, OrderState.FILLED, old_status, "trade")
        else:
            order.status = OrderState.PARTIAL
            self._persist(order, old_status, "trade")
            logger.info(
                f"{BLUE}【部分成交】{RESET} "
                f"订单ID:{order.order_id} 股票:{order.jq_code or order.stock_code} "
                f"成交:{order.filled_quantity}/{order.quantity} "
                f"成交均价:{order.filled_price:.2f}"
            )

        return order

    def update_from_error(
        self,
        order_id: Any,
        error_msg: Optional[str] = None,
    ) -> Optional[TrackedOrder]:
        """处理 xtquant on_order_error 失败回调。"""
        order = self._orders.get(str(order_id))
        if not order:
            return None

        old_status = order.status
        order.error_msg = error_msg
        self._resolve(order, OrderState.FAILED, old_status, "error")
        return order

    def _normalize_status(self, xt_status: Optional[int]) -> str:
        if xt_status == ORDER_SUCCEEDED:
            return OrderState.FILLED
        if xt_status in (ORDER_JUNK, ORDER_CANCELED, ORDER_PART_CANCEL):
            return OrderState.FAILED
        if xt_status == ORDER_PART_SUCC:
            return OrderState.PARTIAL
        return OrderState.PENDING

    def _compute_fill(self, order: TrackedOrder, volume: int, price: float) -> tuple:
        """计算累计成交量和加权成交均价。"""
        if volume <= 0:
            return order.filled_quantity, order.filled_price
        total_amount = order.filled_quantity * order.filled_price + volume * price
        new_qty = order.filled_quantity + volume
        new_price = round(total_amount / new_qty, 4) if new_qty > 0 else 0.0
        return new_qty, new_price

    def _resolve(self, order: TrackedOrder, status: str, from_status: str, source: str) -> None:
        """将订单置为终态并触发回调。"""
        if order.status in (OrderState.FILLED, OrderState.FAILED):
            return

        order.status = status
        order.resolved_at = datetime.now(timezone.utc)
        self._persist(order, from_status, source)

        for callback in self._state_change_callbacks:
            try:
                callback(order)
            except Exception:
                # 回调失败不应影响状态机本身
                pass

    def _persist(self, order: TrackedOrder, from_status: Optional[str], source: str) -> None:
        """持久化订单并记录事件。"""
        self._repo.save(order)
        self._record_event(order, order.status, from_status, source)

    def _record_event(
        self,
        order: TrackedOrder,
        event_type: str,
        from_status: Optional[str],
        source: str,
    ) -> None:
        """记录订单事件。"""
        self._repo.record_event(
            order_id=order.order_id,
            event_type=event_type,
            from_status=from_status,
            to_status=order.status,
            payload={
                "order_id": order.order_id,
                "stock_code": order.stock_code,
                "jq_code": order.jq_code,
                "direction": order.direction,
                "quantity": order.quantity,
                "filled_quantity": order.filled_quantity,
                "filled_price": order.filled_price,
                "status": order.status,
                "xtquant_status": order.xtquant_status,
            },
            source=source,
        )

    def get_order(self, order_id: Any) -> Optional[TrackedOrder]:
        return self._orders.get(str(order_id))

    def get_pending_orders(self) -> List[TrackedOrder]:
        return [
            o for o in self._orders.values()
            if o.status in (OrderState.PENDING, OrderState.PARTIAL)
        ]

    def get_orders_by_strategy(self, strategy_id: Any) -> List[TrackedOrder]:
        target = str(strategy_id)
        return [o for o in self._orders.values() if o.strategy_id == target]

    def list_all(self) -> List[TrackedOrder]:
        """返回内存中所有订单（启动时已从历史记录加载）。"""
        return list(self._orders.values())

    def _load_orders(self) -> None:
        """启动时从 Repository 加载所有历史订单。"""
        for order in self._repo.list_all():
            self._orders[order.order_id] = order

    async def poll_and_reconcile(
        self,
        trader,
        account,
    ) -> List[TrackedOrder]:
        """主动查询 QMT 最新订单状态，修正漏掉的回调。

        返回本次被更新为终态的订单列表。
        """
        pending = self.get_pending_orders()
        if not pending:
            return []

        resolved = []
        order_map: Dict[str, Any] = {}

        try:
            all_orders = trader.query_stock_orders(account, cancelable_only=False)
            for o in all_orders:
                oid = str(getattr(o, 'order_id', ''))
                if oid:
                    order_map[oid] = o
        except Exception:
            order_map = {}

        for order in pending:
            o = order_map.get(order.order_id)
            if not o:
                try:
                    o = trader.query_stock_order(account, order.order_id)
                except Exception:
                    o = None

            if not o:
                continue

            xt_status = getattr(o, 'order_status', None)
            traded_volume = getattr(o, 'traded_volume', 0) or 0
            traded_price = getattr(o, 'traded_price', 0.0) or 0.0
            updated = self.update_from_callback(
                order.order_id, xt_status, traded_volume, traded_price
            )
            if updated and updated.status in (OrderState.FILLED, OrderState.FAILED):
                resolved.append(updated)

        return resolved
