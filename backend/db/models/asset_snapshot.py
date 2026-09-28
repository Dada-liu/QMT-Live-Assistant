"""资产快照数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Numeric, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str


class AssetSnapshotModel(Base):
    __tablename__ = "asset_snapshots"
    __table_args__ = (
        UniqueConstraint("scope", "strategy_id", "ts", name="uq_asset_snapshots_scope_strategy_ts"),
        Index("ix_asset_snapshots_scope_strategy_ts", "scope", "strategy_id", "ts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    scope: Mapped[str] = mapped_column(String(16))
    strategy_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_asset: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    cash: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    market_value: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    daily_pnl: Mapped[float] = mapped_column(Numeric(19, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
