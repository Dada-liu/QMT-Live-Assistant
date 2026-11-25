"""订单事件数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str


class OrderEventModel(Base):
    __tablename__ = "order_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("orders.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[Optional[str]] = mapped_column(String(16))
    to_status: Mapped[Optional[str]] = mapped_column(String(16))
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    source: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
