"""挂起买单数据库模型（调仓资金不足时延迟买入）。"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.db.base import Base, uuid4_str

# 挂起买单状态
PENDING_BUY_WAITING = "waiting"      # 等待卖单回款
PENDING_BUY_SUBMITTED = "submitted"  # 已重新提交为正式订单
PENDING_BUY_EXPIRED = "expired"      # 超时未等到资金
PENDING_BUY_FAILED = "failed"        # 重试失败（策略禁用/删除、持仓校验失败等）

PENDING_BUY_TERMINAL_STATES = (PENDING_BUY_SUBMITTED, PENDING_BUY_EXPIRED, PENDING_BUY_FAILED)


class PendingBuyOrderModel(Base):
    __tablename__ = "pending_buy_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4_str)
    strategy_id: Mapped[str] = mapped_column(String(36), ForeignKey("strategies.id"), index=True)
    method_name: Mapped[str] = mapped_column(String(64))
    stock_code: Mapped[str] = mapped_column(String(16))
    request_payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=PENDING_BUY_WAITING, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    signal_log_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("signal_logs.id"))
    submitted_order_id: Mapped[Optional[str]] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs):
        if kwargs.get("created_at") is None:
            kwargs["created_at"] = datetime.now(timezone.utc)
        super().__init__(**kwargs)
