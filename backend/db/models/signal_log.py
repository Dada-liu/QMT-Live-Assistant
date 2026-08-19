"""信号日志数据库模型。"""
from datetime import datetime, timezone
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
    error_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def __init__(self, **kwargs):
        # id 默认由 SQLAlchemy column default 在 INSERT 时生成，此处提前生成
        # 保证实例化即有 id（InMemory Repository 以 id 为 key，避免多条互相覆盖）
        if kwargs.get("id") is None:
            kwargs["id"] = uuid4_str()
        if kwargs.get("received_at") is None:
            kwargs["received_at"] = datetime.now(timezone.utc)
        if kwargs.get("created_at") is None:
            kwargs["created_at"] = datetime.now(timezone.utc)
        super().__init__(**kwargs)
