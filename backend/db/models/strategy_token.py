"""策略 Token 数据库模型。"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.base import Base, uuid4_str


class StrategyTokenModel(Base):
    __tablename__ = "strategy_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    strategy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("strategies.id"), index=True
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    token_prefix: Mapped[Optional[str]] = mapped_column(String(16))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    strategy: Mapped["StrategyModel"] = relationship("StrategyModel", back_populates="tokens")
