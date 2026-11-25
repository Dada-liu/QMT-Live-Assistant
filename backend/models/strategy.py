"""策略领域模型（Pydantic）。"""
import uuid
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from backend.constants import INSUFFICIENT_FUNDS_REJECT, SECURITY_TYPE_STOCK


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Strategy(BaseModel):
    """策略抽象实体"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    description: str = ""
    enabled: bool = True
    token: str = Field(default_factory=lambda: secrets.token_hex(16))
    allocated_funds: float = 0.0
    available_cash: float = 0.0
    total_asset: float = 0.0
    daily_pnl: float = 0.0
    insufficient_funds_policy: str = INSUFFICIENT_FUNDS_REJECT
    defer_buy_on_insufficient_funds: bool = False
    bark_notify_enabled: bool = True
    default_market_price_type: Literal[5, 44, 45] = 5
    security_type: Literal["stock", "convertible_bond"] = SECURITY_TYPE_STOCK
    last_rollover_date: Optional[str] = None
    positions: list = []
    trading_records: list = []
    deleted_at: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class PositionAssignment(BaseModel):
    """单条持仓分配"""
    stock_code: str
    stock_name: str = ""
    quantity: int = Field(gt=0)
    current_price: float = Field(gt=0)


class StrategyCreate(BaseModel):
    """创建策略请求体"""
    name: str = Field(min_length=1)
    description: str = ""
    allocated_funds: float = Field(gt=0)
    enabled: bool = True
    insufficient_funds_policy: Literal["reject", "max_buyable"] = INSUFFICIENT_FUNDS_REJECT
    defer_buy_on_insufficient_funds: bool = False
    bark_notify_enabled: bool = True
    default_market_price_type: Literal[5, 44, 45] = 5
    security_type: Literal["stock", "convertible_bond"] = SECURITY_TYPE_STOCK
    positions: List[PositionAssignment] = []


class StrategyUpdate(BaseModel):
    """更新策略请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    allocated_funds: Optional[float] = None
    enabled: Optional[bool] = None
    insufficient_funds_policy: Optional[Literal["reject", "max_buyable"]] = None
    defer_buy_on_insufficient_funds: Optional[bool] = None
    bark_notify_enabled: Optional[bool] = None
    default_market_price_type: Optional[Literal[5, 44, 45]] = None
    security_type: Optional[Literal["stock", "convertible_bond"]] = None
    positions: Optional[List[PositionAssignment]] = None
