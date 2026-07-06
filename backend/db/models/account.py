"""账户数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str


class AccountModel(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    account_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_type: Mapped[str] = mapped_column(String(32), default="STOCK")
    qmt_path: Mapped[str] = mapped_column(String(512))
    broker: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
