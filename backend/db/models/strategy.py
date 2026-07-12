"""策略数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, Numeric, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.base import Base


class StrategyModel(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allocated_funds: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    available_cash: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    last_rollover_date: Mapped[Optional[str]] = mapped_column(String(8), default=None)
    trading_records: Mapped[list] = mapped_column(JSON, default=list)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    positions: Mapped[list["PositionModel"]] = relationship(
        "PositionModel", back_populates="strategy", cascade="all, delete-orphan", lazy="selectin"
    )
    tokens: Mapped[list["StrategyTokenModel"]] = relationship(
        "StrategyTokenModel", back_populates="strategy", cascade="all, delete-orphan", lazy="selectin"
    )
