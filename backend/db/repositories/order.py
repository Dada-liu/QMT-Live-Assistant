"""订单 Repository 接口与实现。"""
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.models.order import TrackedOrder, OrderState
from backend.db.models.order import OrderModel
from backend.db.models.order_event import OrderEventModel
from backend.db.base import uuid4_str


class OrderRepository(ABC):
    """订单数据访问抽象。"""

    @abstractmethod
    def get_by_id(self, order_id: str) -> Optional[TrackedOrder]: ...

    @abstractmethod
    def list_pending(self) -> List[TrackedOrder]: ...

    @abstractmethod
    def list_by_strategy(self, strategy_id: str) -> List[TrackedOrder]: ...

    @abstractmethod
    def list_all(self, limit: Optional[int] = None) -> List[TrackedOrder]: ...

    @abstractmethod
    def save(self, order: TrackedOrder) -> TrackedOrder: ...

    @abstractmethod
    def record_event(
        self,
        order_id: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        payload: Optional[dict],
        source: str,
    ) -> None: ...


class InMemoryOrderRepository(OrderRepository):
    """内存订单 Repository，用于测试和无持久化场景。"""

    def __init__(self):
        self._store: dict[str, TrackedOrder] = {}
        self._events: list[dict] = []

    def get_by_id(self, order_id: str) -> Optional[TrackedOrder]:
        order = self._store.get(order_id)
        if order is None:
            return None
        return self._copy(order)

    def list_pending(self) -> List[TrackedOrder]:
        return [
            self._copy(o)
            for o in self._store.values()
            if o.status in (OrderState.PENDING, OrderState.PARTIAL)
        ]

    def list_by_strategy(self, strategy_id: str) -> List[TrackedOrder]:
        return [
            self._copy(o)
            for o in self._store.values()
            if o.strategy_id == strategy_id
        ]

    def list_all(self, limit: Optional[int] = None) -> List[TrackedOrder]:
        orders = list(self._store.values())
        if limit is not None:
            orders = orders[-limit:]
        return [self._copy(o) for o in orders]

    def save(self, order: TrackedOrder) -> TrackedOrder:
        copied = self._copy(order)
        self._store[copied.order_id] = copied
        return self._copy(copied)

    def record_event(
        self,
        order_id: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        payload: Optional[dict],
        source: str,
    ) -> None:
        self._events.append({
            "order_id": order_id,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "payload": deepcopy(payload),
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _copy(order: TrackedOrder) -> TrackedOrder:
        new_order = replace(order)
        new_order.optimistic_snapshot = getattr(order, "optimistic_snapshot", None)
        return new_order


class SQLAlchemyOrderRepository(OrderRepository):
    """SQLAlchemy 订单 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, order_id: str) -> Optional[TrackedOrder]:
        row = (
            self._session.query(OrderModel)
            .filter_by(external_order_id=order_id)
            .first()
        )
        return self._to_domain(row) if row else None

    def list_pending(self) -> List[TrackedOrder]:
        rows = (
            self._session.query(OrderModel)
            .filter(OrderModel.status.in_([OrderState.PENDING, OrderState.PARTIAL]))
            .all()
        )
        return [self._to_domain(row) for row in rows]

    def list_by_strategy(self, strategy_id: str) -> List[TrackedOrder]:
        rows = (
            self._session.query(OrderModel)
            .filter_by(strategy_id=strategy_id)
            .order_by(OrderModel.placed_at.desc())
            .all()
        )
        return [self._to_domain(row) for row in rows]

    def list_all(self, limit: Optional[int] = None) -> List[TrackedOrder]:
        query = (
            self._session.query(OrderModel)
            .order_by(OrderModel.placed_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        return [self._to_domain(row) for row in query.all()]

    def save(self, order: TrackedOrder) -> TrackedOrder:
        existing = (
            self._session.query(OrderModel)
            .filter_by(external_order_id=order.order_id)
            .first()
        )
        if existing is None:
            model = self._to_model(order)
            self._session.add(model)
            self._session.flush()
            self._session.refresh(model)
            saved_row = model
        else:
            self._update_model(existing, order)
            self._session.flush()
            self._session.refresh(existing)
            saved_row = existing
        self._session.commit()
        return self._to_domain(saved_row)

    def record_event(
        self,
        order_id: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        payload: Optional[dict],
        source: str,
    ) -> None:
        event = OrderEventModel(
            order_id=self._resolve_internal_id(order_id),
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            payload=deepcopy(payload),
            source=source,
        )
        self._session.add(event)
        self._session.commit()

    def _to_domain(self, row: OrderModel) -> TrackedOrder:
        order = TrackedOrder(
            order_id=row.external_order_id or row.id,
            stock_code=row.stock_code,
            jq_code=row.source_code or "",
            direction=row.direction,
            quantity=row.quantity,
            order_type=row.order_type,
            strategy_id=row.strategy_id,
            strategy_name=row.strategy_name or "",
            price=float(row.price),
            status=row.status,
            xtquant_status=None,
            filled_quantity=row.filled_quantity,
            filled_price=float(row.filled_price),
            placed_at=row.placed_at or datetime.now(timezone.utc),
            resolved_at=row.resolved_at,
            error_msg=row.error_msg,
            optimistic_position_applied=row.optimistic_position_applied or False,
            optimistic_snapshot=row.optimistic_snapshot,
        )
        return order

    def _to_model(self, order: TrackedOrder) -> OrderModel:
        return OrderModel(
            id=uuid4_str(),
            account_id="",  # Phase 1 单账户
            external_order_id=order.order_id,
            stock_code=order.stock_code,
            source_code=order.jq_code,
            source_platform=None,
            direction=order.direction,
            order_type=order.order_type,
            price=order.price,
            quantity=order.quantity,
            filled_quantity=order.filled_quantity,
            filled_price=order.filled_price,
            filled_amount=order.filled_quantity * order.filled_price,
            status=order.status,
            placed_at=order.placed_at,
            resolved_at=order.resolved_at,
            strategy_id=order.strategy_id,
            strategy_name=order.strategy_name,
            optimistic_position_applied=order.optimistic_position_applied,
            optimistic_snapshot=order.optimistic_snapshot,
        )

    def _update_model(self, model: OrderModel, order: TrackedOrder) -> None:
        model.stock_code = order.stock_code
        model.source_code = order.jq_code
        model.direction = order.direction
        model.order_type = order.order_type
        model.price = order.price
        model.quantity = order.quantity
        model.filled_quantity = order.filled_quantity
        model.filled_price = order.filled_price
        model.filled_amount = order.filled_quantity * order.filled_price
        model.status = order.status
        model.resolved_at = order.resolved_at
        model.error_msg = order.error_msg
        model.optimistic_position_applied = order.optimistic_position_applied
        model.optimistic_snapshot = order.optimistic_snapshot
        model.updated_at = datetime.now(timezone.utc)

    def _resolve_internal_id(self, order_id: str) -> str:
        row = (
            self._session.query(OrderModel)
            .filter_by(external_order_id=order_id)
            .first()
        )
        return row.id if row else order_id
