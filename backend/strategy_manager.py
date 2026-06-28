"""策略管理器。

管理多个远程交易策略，支持策略 CRUD、资金分配、持仓跟踪、
交易记录，以及基于 QMT 实时行情的持仓富化和当日盈亏计算。
"""
import uuid
import secrets
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from backend.utils import fetch_preclose_from_xtdata, fetch_open_prices_from_xtdata, fetch_stock_names_from_xtdata


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
    positions: List[PositionAssignment] = []


class StrategyUpdate(BaseModel):
    """更新策略请求体"""
    name: Optional[str] = None
    description: Optional[str] = None
    allocated_funds: Optional[float] = None
    enabled: Optional[bool] = None
    positions: Optional[List[PositionAssignment]] = None


class StrategyManager:
    """策略管理器 — 管理所有策略的生命周期和资金持仓跟踪"""

    def __init__(self):
        self._strategies: Dict[str, Strategy] = {}
        self._signal_counts: Dict[str, int] = {}
        self._daily_profit: float = 0.0

    @property
    def daily_profit(self) -> float:
        return self._daily_profit

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
        # 初始化分配持仓（成本价取 xtquant 开盘价，行情数据实时获取）
        if data.positions:
            codes = [pa.stock_code for pa in data.positions]
            open_prices = fetch_open_prices_from_xtdata(codes)
            total_cost = 0.0
            pos_list = []
            for pa in data.positions:
                open_price = open_prices.get(pa.stock_code) or pa.current_price
                cost = pa.quantity * open_price
                total_cost += cost
                pos_list.append({
                    "stock_code": pa.stock_code,
                    "stock_name": pa.stock_name,
                    "quantity": pa.quantity,
                    "avg_cost": open_price,
                })
            if total_cost > data.allocated_funds:
                raise ValueError(f"持仓总成本({total_cost:.2f})超过分配金额({data.allocated_funds:.2f})")
            strategy.positions = pos_list
            strategy.available_cash = data.allocated_funds - total_cost

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

        # 先处理 positions（在对 allocated_funds 之前），
        # 因为 positions 变化会影响 available_cash 的计算基础
        positions_value = update_data.pop("positions", None)

        for key, value in update_data.items():
            if key == "allocated_funds":
                diff = value - strategy.allocated_funds
                strategy.allocated_funds = value
                strategy.available_cash += diff
            else:
                setattr(strategy, key, value)

        # 处理持仓重新分配（成本价结合 xtquant open_price 和已有成本综合计算）
        if positions_value is not None:
            # 获取所有涉及股票的开盘价
            codes = set(pa["stock_code"] for pa in positions_value)
            codes.update(pos["stock_code"] for pos in strategy.positions)
            open_prices = fetch_open_prices_from_xtdata(codes)

            new_by_code = {}
            for pa in positions_value:
                code = pa["stock_code"]
                open_price = open_prices.get(code) or pa.get("current_price", 0)
                new_by_code[code] = {
                    "stock_code": code,
                    "stock_name": pa.get("stock_name", ""),
                    "quantity": pa["quantity"],
                    "avg_cost": open_price,
                }

            kept = []
            for pos in strategy.positions:
                code = pos["stock_code"]
                if code in new_by_code:
                    old_qty = pos["quantity"]
                    old_avg = pos["avg_cost"]
                    new_pos = new_by_code[code]
                    new_qty = new_pos["quantity"]
                    open_price = open_prices.get(code) or new_pos["avg_cost"]

                    if new_qty > old_qty:
                        # 加仓：加权平均 (旧成本 × 旧数量 + 开盘价 × 增量) / 新数量
                        new_pos["avg_cost"] = round(
                            (old_qty * old_avg + (new_qty - old_qty) * open_price) / new_qty, 4
                        )
                    else:
                        # 减仓或不变：保留原成本价
                        new_pos["avg_cost"] = old_avg

                    old_cost = old_qty * old_avg
                    new_cost = new_pos["avg_cost"] * new_qty
                    strategy.available_cash += (old_cost - new_cost)
                    kept.append(new_pos)
                    del new_by_code[code]
                else:
                    strategy.available_cash += pos["avg_cost"] * pos["quantity"]

            # 新增持仓：成本价取 open_price
            for new_pos in new_by_code.values():
                open_price = open_prices.get(new_pos["stock_code"]) or new_pos["avg_cost"]
                new_pos["avg_cost"] = open_price
                strategy.available_cash -= open_price * new_pos["quantity"]
                kept.append(new_pos)

            if strategy.available_cash < 0:
                raise ValueError("可用资金不足，无法完成持仓分配")

            strategy.positions = kept

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
        """更新策略持仓数量和可用资金（买卖信号执行后调用），行情数据由 list_all_enriched 实时计算"""
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
                    found = True
                    break
            if not found:
                positions.append({
                    "stock_code": stock_code,
                    "stock_name": "",
                    "quantity": quantity,
                    "avg_cost": price,
                })
        elif direction == "sell":
            strategy.available_cash += cost
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    pos["quantity"] -= quantity
                    if pos["quantity"] <= 0:
                        positions = [p for p in positions if p["stock_code"] != stock_code]
                    break

        strategy.positions = positions
        strategy.updated_at = datetime.now().isoformat()

    def add_trading_record(self, strategy_id: str, record: dict):
        """添加买卖记录"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return
        records = list(strategy.trading_records)
        records.append(record)
        strategy.trading_records = records

    def list_all_enriched(self, trader, account) -> List[dict]:
        """列出所有策略，并用 QMT 实时行情数据富化持仓（current_price/market_value/daily_pnl）"""
        if not self._strategies:
            return []

        # 从 QMT 获取实时持仓行情
        qmt_positions = []
        try:
            qmt_positions_raw = trader.query_stock_positions(account)
            for p in qmt_positions_raw:
                if hasattr(p, '__dir__'):
                    qmt_positions.append({
                        "stock_code": getattr(p, 'stock_code', ''),
                        "volume": getattr(p, 'volume', 0) or 0,
                        "market_value": getattr(p, 'market_value', 0.0) or 0.0,
                    })
                elif isinstance(p, dict):
                    qmt_positions.append(p)
        except Exception:
            pass

        # 收集所有策略涉及的股票代码，从行情模块批量获取前收盘价
        all_codes = {pos["stock_code"] for s in self._strategies.values() for pos in s.positions if pos["stock_code"]}
        preclose_map = fetch_preclose_from_xtdata(all_codes)

        # 构建 QMT 数据索引 {stock_code: {market_value, volume, current_price}}
        qmt_index = {}
        for p in qmt_positions:
            code = p.get("stock_code", "")
            if not code:
                continue
            vol = p.get("volume", 0)
            mv = p.get("market_value", 0.0)
            qmt_index[code] = {
                "volume": vol,
                "market_value": mv,
                "current_price": round(mv / vol, 2) if vol > 0 else 0.0,
            }

        global_daily_profit = 0.0
        result = []
        for s in self._strategies.values():
            d = s.model_dump()
            d["signal_count"] = self._signal_counts.get(s.id, 0)

            daily_pnl_total = 0.0
            enriched_positions = []
            for pos in s.positions:
                code = pos["stock_code"]
                enriched = dict(pos)  # 拷贝原始字段：stock_code, stock_name, quantity, avg_cost

                qty = pos["quantity"]
                qmt_data = qmt_index.get(code)
                qmt_vol = qmt_data["volume"] if qmt_data else 0

                # 最新价：从 QMT 市值/数量计算
                if qmt_data and qmt_data["current_price"] > 0:
                    enriched["current_price"] = qmt_data["current_price"]
                else:
                    enriched["current_price"] = 0.0

                # 计算市值：按策略占比分配 QMT 市值
                if qmt_data and qmt_vol > 0:
                    ratio = qty / qmt_vol
                    enriched["market_value"] = round(qmt_data["market_value"] * ratio, 2)
                else:
                    enriched["market_value"] = round(enriched["current_price"] * qty, 2)
                # 计算当日盈亏：(市值 - 前收盘价 × 数量)
                preclose = preclose_map.get(code)
                mv = enriched["market_value"]
                if preclose is not None and preclose > 0 and qty > 0:
                    pos_daily_pnl = round(mv - preclose * qty, 2)
                else:
                    pos_daily_pnl = 0.0
                enriched["daily_pnl"] = pos_daily_pnl
                daily_pnl_total += pos_daily_pnl

                # 累计盈亏 = 市值 - 成本价 × 数量
                avg_cost = pos.get("avg_cost", 0)
                enriched["total_pnl"] = round(mv - avg_cost * qty, 2) if qty > 0 else 0.0

                enriched_positions.append(enriched)

            d["positions"] = enriched_positions
            d["daily_pnl"] = round(daily_pnl_total, 2)
            d["total_asset"] = round(s.available_cash + sum(
                p["market_value"] for p in enriched_positions
            ), 2)

            global_daily_profit += daily_pnl_total
            result.append(d)

        self._daily_profit = round(global_daily_profit, 2)
        return result
