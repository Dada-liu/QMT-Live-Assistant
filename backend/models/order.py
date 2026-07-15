"""订单领域模型。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


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
