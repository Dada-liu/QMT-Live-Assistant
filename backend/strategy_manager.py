"""
策略管理器 — 管理多个远程交易策略
每个策略代表一个独立的交易策略，可独立启用/禁用，
拥有独立的 token、资金分配、持仓跟踪和交易记录。
"""
import uuid
import secrets
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


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
    positions: list = []
    trading_records: list = []
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class StrategyCreate(BaseModel):
    """创建策略请求体"""
    name: str
    description: str = ""
    allocated_funds: float = 0.0
    enabled: bool = True


class StrategyUpdate(BaseModel):
    """更新策略请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    allocated_funds: Optional[float] = None
    enabled: Optional[bool] = None


class StrategyManager:
    """策略管理器 — 管理所有策略的生命周期和资金持仓跟踪"""

    def __init__(self):
        self._strategies: Dict[str, Strategy] = {}
        self._signal_counts: Dict[str, int] = {}

    def create(self, data: StrategyCreate) -> Strategy:
        """创建新策略"""
        strategy = Strategy(
            name=data.name,
            description=data.description,
            allocated_funds=data.allocated_funds,
            available_cash=data.allocated_funds,
            total_asset=data.allocated_funds,
            enabled=data.enabled,
        )
        self._strategies[strategy.id] = strategy
        self._signal_counts[strategy.id] = 0
        return strategy

    def get(self, strategy_id: str) -> Optional[Strategy]:
        """获取单个策略"""
        return self._strategies.get(strategy_id)

    def find_by_token(self, token: str) -> Optional[Strategy]:
        """根据 token 查找策略"""
        for s in self._strategies.values():
            if s.token == token:
                return s
        return None

    def list_all(self) -> List[dict]:
        """列出所有策略（含信号计数）"""
        result = []
        for s in self._strategies.values():
            d = s.model_dump()
            d["signal_count"] = self._signal_counts.get(s.id, 0)
            result.append(d)
        return result

    def update(self, strategy_id: str, data: StrategyUpdate) -> Optional[Strategy]:
        """更新策略"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == "allocated_funds":
                diff = value - strategy.allocated_funds
                strategy.allocated_funds = value
                strategy.available_cash += diff
                strategy.total_asset = strategy.available_cash + sum(
                    p.get("market_value", 0) for p in strategy.positions
                )
            else:
                setattr(strategy, key, value)
        strategy.updated_at = datetime.now().isoformat()
        self._strategies[strategy_id] = strategy
        return strategy

    def delete(self, strategy_id: str) -> bool:
        """删除策略"""
        if strategy_id in self._strategies:
            del self._strategies[strategy_id]
            self._signal_counts.pop(strategy_id, None)
            return True
        return False

    def toggle(self, strategy_id: str) -> Optional[Strategy]:
        """切换启用/禁用"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return None
        strategy.enabled = not strategy.enabled
        strategy.updated_at = datetime.now().isoformat()
        return strategy

    def is_enabled(self, strategy_id: str) -> bool:
        """检查策略是否启用"""
        strategy = self._strategies.get(strategy_id)
        return strategy is not None and strategy.enabled

    def increment_signal_count(self, strategy_id: str):
        """增加策略信号计数"""
        if strategy_id in self._signal_counts:
            self._signal_counts[strategy_id] += 1

    def get_signal_count(self, strategy_id: str) -> int:
        """获取策略信号计数"""
        return self._signal_counts.get(strategy_id, 0)

    def update_position(self, strategy_id: str, stock_code: str,
                        direction: str, quantity: int, price: float):
        """更新策略持仓数量和可用资金（买卖信号执行后调用）"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return

        positions = list(strategy.positions)
        cost = quantity * price

        if direction == "buy":
            strategy.available_cash -= cost
            found = False
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    total_qty = pos["quantity"] + quantity
                    total_cost = pos["avg_cost"] * pos["quantity"] + cost
                    pos["quantity"] = total_qty
                    pos["avg_cost"] = round(total_cost / total_qty, 4) if total_qty > 0 else 0
                    pos["market_value"] = total_qty * price
                    found = True
                    break
            if not found:
                positions.append({
                    "stock_code": stock_code,
                    "stock_name": "",
                    "quantity": quantity,
                    "avg_cost": price,
                    "current_price": price,
                    "market_value": cost,
                    "daily_pnl": 0.0,
                })
        elif direction == "sell":
            strategy.available_cash += cost
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    pos["quantity"] -= quantity
                    if pos["quantity"] <= 0:
                        positions = [p for p in positions if p["stock_code"] != stock_code]
                    else:
                        pos["market_value"] = pos["quantity"] * pos["current_price"]
                    break

        strategy.positions = positions
        strategy.total_asset = strategy.available_cash + sum(
            p.get("market_value", 0) for p in positions
        )
        strategy.updated_at = datetime.now().isoformat()

    def add_trading_record(self, strategy_id: str, record: dict):
        """添加买卖记录"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return
        records = list(strategy.trading_records)
        records.append(record)
        strategy.trading_records = records

    def refresh_from_qmt(self, trader, account):
        """从 QMT 查询实时持仓行情，更新所有策略的持仓市值和当日盈亏"""
        try:
            qmt_positions_raw = trader.query_stock_positions(account)
        except Exception:
            return

        qmt_positions = []
        for p in qmt_positions_raw:
            if hasattr(p, '__dir__'):
                qmt_positions.append({
                    "stock_code": getattr(p, 'stock_code', ''),
                    "volume": getattr(p, 'volume', 0) or getattr(p, 'amount', 0) or 0,
                    "market_value": getattr(p, 'market_value', 0.0) or 0.0,
                    "current_price": getattr(p, 'last_price', 0.0) or getattr(p, 'price', 0.0) or 0.0,
                    "daily_pnl": getattr(p, 'income_today', 0.0) or getattr(p, 'profit', 0.0) or 0.0,
                })
            elif isinstance(p, dict):
                qmt_positions.append(p)

        if not qmt_positions:
            return

        # 计算每个标的所有策略总持仓
        stock_total_qty: Dict[str, int] = {}
        for strategy in self._strategies.values():
            for pos in strategy.positions:
                code = pos["stock_code"]
                stock_total_qty[code] = stock_total_qty.get(code, 0) + pos["quantity"]

        # 按比例分配 QMT 行情数据到各策略
        for strategy in self._strategies.values():
            daily_pnl_total = 0.0
            updated_positions = []
            for pos in strategy.positions:
                code = pos["stock_code"]
                total_qty = stock_total_qty.get(code, 0)
                qmt_pos = next((p for p in qmt_positions if p["stock_code"] == code), None)
                if qmt_pos and total_qty > 0:
                    ratio = pos["quantity"] / total_qty
                    pos["current_price"] = qmt_pos["current_price"]
                    pos["market_value"] = round(qmt_pos["market_value"] * ratio, 2)
                    pos["daily_pnl"] = round(qmt_pos["daily_pnl"] * ratio, 2)
                    daily_pnl_total += pos["daily_pnl"]
                updated_positions.append(pos)

            strategy.positions = updated_positions
            strategy.daily_pnl = round(daily_pnl_total, 2)
            strategy.total_asset = strategy.available_cash + sum(
                p.get("market_value", 0) for p in updated_positions
            )
            strategy.updated_at = datetime.now().isoformat()
