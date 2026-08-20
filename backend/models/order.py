"""订单领域模型。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
    price_type: Optional[int] = None  # 报价类型：5=最新价，11=限价，44=对手方最优，45=本方最优
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
    notify_source: bool = False
    source_platform_webhook: Optional[str] = None
    source_platform: Optional[str] = None


class OrderResendRequest(BaseModel):
    """重发订单请求体，可选覆盖原下单参数。"""
    quantity: Optional[int] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, ge=0)
    price_type: Optional[int] = Field(
        default=None,
        description="报价类型：5=最新价，11=限价，44=对手方最优，45=本方最优；默认沿用原订单报价方式",
    )


class ManualOrderRequest(BaseModel):
    """Web UI 手动下单请求体（主 Token）。"""
    stock_code: str = Field(min_length=1)
    direction: str = Field(min_length=1)      # 'buy' | 'sell'，端点内手动校验 → 400
    quantity: int = Field(gt=0)
    price: float = Field(default=0.0, ge=0)   # 0 表示市价
    price_type: Optional[int] = Field(
        default=None,
        description="报价类型：5=最新价，11=限价，44=对手方最优，45=本方最优；默认由 price 与策略配置推导",
    )
    notify_source: bool = Field(
        default=False,
        description="是否在订单状态变更时通知源平台",
    )
    source_platform_webhook: Optional[str] = Field(
        default=None,
        description="源平台回调地址",
    )
    source_platform: Optional[str] = Field(
        default=None,
        description="源平台标识，用于全局 webhook 映射",
    )


class GenericOrderRequest(BaseModel):
    """通用下单请求体（策略 Token）。

    支持业务层全参数下单，字段覆盖方向、数量、价格、价格类型、委托类型、
    策略上下文、订单备注与信号来源平台。
    """
    security: str = Field(min_length=1, description="证券代码，支持 QMT/聚宽/6位数字格式")
    quantity: int = Field(gt=0, description="委托数量")
    direction: str = Field(default="buy", description="下单方向：buy 或 sell")
    price: float = Field(default=0.0, ge=0, description="委托价格，0 表示市价/最新价")
    price_type: Optional[int] = Field(
        default=None,
        description="报价类型：5=最新价，11=限价，44=对手方最优，45=本方最优，42-48=交易所市价（仅实盘生效）；默认由 price 与策略配置推导",
    )
    order_type: Optional[int] = Field(
        default=None,
        description="xtquant 委托类型，如 STOCK_BUY=23, STOCK_SELL=24",
    )
    strategy_name: Optional[str] = Field(
        default="generic_order",
        min_length=1,
        description="写入 QMT 订单备注的策略名称",
    )
    order_remark: Optional[str] = Field(
        default="",
        description="QMT 订单备注",
    )
    side: Optional[str] = Field(
        default="long",
        description="仅对期货空头逻辑生效：long 或 short",
    )
    source_platform: Optional[str] = Field(
        default=None,
        description="信号来源平台，用于信号日志与 webhook 映射",
    )
    notify_source: bool = Field(
        default=False,
        description="是否在订单状态变更时通知源平台",
    )
    source_platform_webhook: Optional[str] = Field(
        default=None,
        description="源平台回调地址",
    )

    @field_validator("security")
    @classmethod
    def strip_security(cls, v: str) -> str:
        return v.strip()

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ("buy", "sell"):
            raise ValueError("direction 必须为 buy 或 sell")
        return v

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("long", "short"):
            raise ValueError("side 必须为 long 或 short")
        return v


class JukuanOrderRequest(BaseModel):
    """聚宽风格按数量下单请求体（策略 Token）。"""
    security: str = Field(min_length=1, description="证券代码，支持 QMT/聚宽/6位数字格式")
    amount: int = Field(description="目标数量，正数买入/开多，负数卖出/平多")
    side: Literal["long", "short"] = Field(default="long", description="仅对期货空头逻辑生效：long 或 short")
    source_platform: Optional[str] = Field(
        default=None,
        description="信号来源平台，用于信号日志与 webhook 映射",
    )
    notify_source: bool = Field(
        default=False,
        description="是否在订单状态变更时通知源平台",
    )
    source_platform_webhook: Optional[str] = Field(
        default=None,
        description="源平台回调地址",
    )

    @field_validator("security")
    @classmethod
    def strip_security(cls, v: str) -> str:
        return v.strip()


class JukuanOrderTargetRequest(BaseModel):
    """聚宽风格目标持仓数量调仓请求体（策略 Token）。"""
    security: str = Field(min_length=1, description="证券代码，支持 QMT/聚宽/6位数字格式")
    amount: int = Field(ge=0, description="目标持仓数量，必须大于等于 0")
    side: Literal["long", "short"] = Field(default="long", description="仅对期货空头逻辑生效：long 或 short")
    source_platform: Optional[str] = Field(default=None, description="信号来源平台")
    notify_source: bool = Field(default=False, description="是否在订单状态变更时通知源平台")
    source_platform_webhook: Optional[str] = Field(default=None, description="源平台回调地址")

    @field_validator("security")
    @classmethod
    def strip_security(cls, v: str) -> str:
        return v.strip()


class JukuanOrderValueRequest(BaseModel):
    """聚宽风格按金额下单请求体（策略 Token）。"""
    security: str = Field(min_length=1, description="证券代码，支持 QMT/聚宽/6位数字格式")
    value: float = Field(description="目标金额，正数买入，负数卖出")
    side: Literal["long", "short"] = Field(default="long", description="仅对期货空头逻辑生效：long 或 short")
    source_platform: Optional[str] = Field(default=None, description="信号来源平台")
    notify_source: bool = Field(default=False, description="是否在订单状态变更时通知源平台")
    source_platform_webhook: Optional[str] = Field(default=None, description="源平台回调地址")

    @field_validator("security")
    @classmethod
    def strip_security(cls, v: str) -> str:
        return v.strip()


class JukuanOrderTargetValueRequest(BaseModel):
    """聚宽风格目标持仓市值调仓请求体（策略 Token）。"""
    security: str = Field(min_length=1, description="证券代码，支持 QMT/聚宽/6位数字格式")
    value: float = Field(description="目标持仓市值")
    side: Literal["long", "short"] = Field(default="long", description="仅对期货空头逻辑生效：long 或 short")
    source_platform: Optional[str] = Field(default=None, description="信号来源平台")
    notify_source: bool = Field(default=False, description="是否在订单状态变更时通知源平台")
    source_platform_webhook: Optional[str] = Field(default=None, description="源平台回调地址")

    @field_validator("security")
    @classmethod
    def strip_security(cls, v: str) -> str:
        return v.strip()
