"""策略持仓数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.base import Base, uuid4_str


class PositionModel(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id"), index=True
    )
    stock_code: Mapped[str] = mapped_column(String(16))
    stock_name: Mapped[Optional[str]] = mapped_column(String(64))
    direction: Mapped[Optional[str]] = mapped_column(String(8), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    available_quantity: Mapped[int] = mapped_column(Integer, default=0)
    frozen_quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    yesterday_quantity: Mapped[int] = mapped_column(Integer, default=0)
    yesterday_close: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    today_bought_quantity: Mapped[int] = mapped_column(Integer, default=0)
    today_bought_cost: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    strategy: Mapped["StrategyModel"] = relationship("StrategyModel", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("strategy_id", "stock_code", "direction", name="uix_position"),
    )
