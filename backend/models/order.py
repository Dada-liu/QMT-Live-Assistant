"""订单领域模型。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class OrderState:
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    FAILED = "failed"


@dataclass
class TrackedOrder:
    order_id: str
    stock_code: str          # QMT 代码
    jq_code: str             # 聚宽代码
    direction: str           # "buy" 或 "sell"
    quantity: int            # 委托数量
    order_type: int          # xtquant 委托类型（如 STOCK_BUY=23）
    strategy_id: Optional[str]
    strategy_name: str
    price: float             # 委托价格，市价单为 0
    stock_name: str = ""     # 股票名称，从 xtdata 获取
    status: str = OrderState.PENDING
    xtquant_status: Optional[int] = None
    filled_quantity: int = 0
    filled_price: float = 0.0
    placed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    optimistic_position_applied: bool = False
    optimistic_snapshot: Optional[dict] = None
    retried_as_order_id: Optional[str] = None


class OrderResendRequest(BaseModel):
    """重发订单请求体，可选覆盖原下单参数。"""
    quantity: Optional[int] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, ge=0)


class ManualOrderRequest(BaseModel):
    """Web UI 手动下单请求体（主 Token）。"""
    stock_code: str = Field(min_length=1)
    direction: str = Field(min_length=1)      # 'buy' | 'sell'，端点内手动校验 → 400
    quantity: int = Field(gt=0)
    price: float = Field(default=0.0, ge=0)   # 0 表示市价
