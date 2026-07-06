"""订单数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str


class OrderModel(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("strategies.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("accounts.id"), index=True)
    external_order_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    order_sysid: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    stock_code: Mapped[str] = mapped_column(String(16))
    source_code: Mapped[Optional[str]] = mapped_column(String(24))
    source_platform: Mapped[Optional[str]] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    offset_flag: Mapped[Optional[str]] = mapped_column(String(16))
    order_type: Mapped[int] = mapped_column(Integer)
    price_type: Mapped[Optional[int]] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    filled_price: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    filled_amount: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    status_msg: Mapped[Optional[str]] = mapped_column(Text)
    error_code: Mapped[Optional[str]] = mapped_column(String(32))
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    exchange_order_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    strategy_name: Mapped[Optional[str]] = mapped_column(String(128))
    order_remark: Mapped[Optional[str]] = mapped_column(String(64))
    request_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    response_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
