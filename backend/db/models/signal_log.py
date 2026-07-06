"""信号日志数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str


class SignalLogModel(Base):
    __tablename__ = "signal_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    strategy_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("strategies.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    source_platform: Mapped[Optional[str]] = mapped_column(String(32))
    source_ip: Mapped[Optional[str]] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    processed_order_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("orders.id"), index=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
