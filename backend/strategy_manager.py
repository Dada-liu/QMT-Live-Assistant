"""策略管理器。

管理多个远程交易策略，支持策略 CRUD、资金分配、持仓跟踪、
交易记录，以及基于 QMT 实时行情的持仓富化和当日盈亏计算。
"""
from datetime import datetime, timezone
from typing import Dict, List, Optional
from backend.utils import fetch_preclose_from_xtdata, fetch_open_prices_from_xtdata, fetch_stock_names_from_xtdata
from backend.db.repositories.strategy import StrategyRepository, InMemoryStrategyRepository
from backend.models.strategy import Strategy, StrategyCreate, StrategyUpdate, PositionAssignment


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_position(stock_code: str, stock_name: str, quantity: int, avg_cost: float,
                   available_quantity: Optional[int] = None,
                   frozen_quantity: int = 0) -> dict:
    """构造标准化持仓字典。"""
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "quantity": quantity,
        "available_quantity": available_quantity if available_quantity is not None else quantity,
        "frozen_quantity": frozen_quantity,
        "avg_cost": avg_cost,
    }


class StrategyManager:
    """策略管理器 — 管理所有策略的生命周期和资金持仓跟踪"""

    def __init__(self, repository: Optional[StrategyRepository] = None):
        self._repo = repository or InMemoryStrategyRepository()
        self._daily_profit: float = 0.0
        self._strategies: Dict[str, Strategy] = {}
        self._refresh_cache()

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
        if data.positions:
            codes = [pa.stock_code for pa in data.positions]
            open_prices = fetch_open_prices_from_xtdata(codes)
            total_cost = 0.0
            pos_list = []
            for pa in data.positions:
                open_price = open_prices.get(pa.stock_code) or pa.current_price
                cost = pa.quantity * open_price
                total_cost += cost
                pos_list.append(_make_position(
                    stock_code=pa.stock_code,
                    stock_name=pa.stock_name,
                    quantity=pa.quantity,
                    avg_cost=open_price,
                ))
            if total_cost > data.allocated_funds:
                raise ValueError(f"持仓总成本({total_cost:.2f})超过分配金额({data.allocated_funds:.2f})")
            strategy = strategy.model_copy(update={
                "positions": pos_list,
                "available_cash": data.allocated_funds - total_cost,
            })

        return self._persist(strategy)

    def get(self, strategy_id: str) -> Optional[Strategy]:
        """获取单个策略"""
        return self._strategies.get(strategy_id)

    def find_by_token(self, token: str) -> Optional[Strategy]:
        """根据 token 查找策略"""
        return self._repo.get_by_token(token)

    def list_all(self) -> List[dict]:
        """列出所有策略"""
        result = []
        for s in self._strategies.values():
            d = s.model_dump()
            result.append(d)
        return result

    def update(self, strategy_id: str, data: StrategyUpdate) -> Optional[Strategy]:
        """更新策略"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return None
        update_data = data.model_dump(exclude_unset=True)
        positions_value = update_data.pop("positions", None)

        if "allocated_funds" in update_data:
            diff = update_data["allocated_funds"] - strategy.allocated_funds
            update_data["available_cash"] = strategy.available_cash + diff

        update_data["updated_at"] = _now_iso()

        if positions_value is not None:
            new_positions, new_cash = self._rebuild_positions(
                strategy.positions, positions_value, strategy.available_cash
            )
            update_data["positions"] = new_positions
            update_data["available_cash"] = new_cash

        new_strategy = strategy.model_copy(deep=True, update=update_data)
        return self._persist(new_strategy)

    def delete(self, strategy_id: str) -> bool:
        """删除策略"""
        result = self._repo.delete(strategy_id)
        if result:
            self._strategies.pop(strategy_id, None)
        return result

    def toggle(self, strategy_id: str) -> Optional[Strategy]:
        """切换启用/禁用"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return None
        new_strategy = strategy.model_copy(update={
            "enabled": not strategy.enabled,
            "updated_at": _now_iso(),
        })
        return self._persist(new_strategy)

    def is_enabled(self, strategy_id: str) -> bool:
        """检查策略是否启用"""
        strategy = self._strategies.get(strategy_id)
        return strategy is not None and strategy.enabled

    def update_position(self, strategy_id: str, stock_code: str,
                        direction: str, quantity: int, price: float):
        """按实际成交更新策略持仓（可用数量和总数量同步变更）。"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return

        new_positions, new_cash = self._apply_actual_fill(
            strategy.positions,
            strategy.available_cash,
            stock_code,
            direction,
            quantity,
            price,
        )
        new_strategy = strategy.model_copy(update={
            "positions": new_positions,
            "available_cash": new_cash,
            "updated_at": _now_iso(),
        })
        self._persist(new_strategy)

    def apply_optimistic_position(self, strategy_id: str, stock_code: str,
                                  direction: str, quantity: int, price: float):
        """下单时冻结对应数量，并返回更新前的持仓快照用于后续回滚或修正。

        买入/卖出委托未成交期间：
        - 总数量 quantity 不变
        - 可用数量 available_quantity 减少
        - 冻结数量 frozen_quantity 增加
        - 可用资金按委托金额预先扣减/增加
        """
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return None

        old_pos = next(
            (p for p in strategy.positions if p["stock_code"] == stock_code), None
        )
        snapshot = {
            "stock_code": stock_code,
            "quantity": old_pos["quantity"] if old_pos else 0,
            "available_quantity": old_pos["available_quantity"] if old_pos else 0,
            "frozen_quantity": old_pos["frozen_quantity"] if old_pos else 0,
            "avg_cost": old_pos["avg_cost"] if old_pos else 0.0,
            "available_cash": strategy.available_cash,
        }

        new_positions, new_cash = self._freeze_position(
            strategy.positions,
            strategy.available_cash,
            stock_code,
            direction,
            quantity,
            price,
        )
        new_strategy = strategy.model_copy(update={
            "positions": new_positions,
            "available_cash": new_cash,
            "updated_at": _now_iso(),
        })
        self._persist(new_strategy)
        return snapshot

    def rollback_position(self, strategy_id: str, snapshot: Optional[dict]):
        """根据快照撤销乐观持仓更新（解冻）。"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy or not snapshot:
            return

        positions = [
            p for p in strategy.positions
            if p["stock_code"] != snapshot["stock_code"]
        ]
        total_qty = snapshot["quantity"] + snapshot["frozen_quantity"]
        if total_qty > 0:
            positions.append(_make_position(
                stock_code=snapshot["stock_code"],
                stock_name="",
                quantity=snapshot["quantity"],
                avg_cost=snapshot["avg_cost"],
                available_quantity=snapshot["available_quantity"],
                frozen_quantity=snapshot["frozen_quantity"],
            ))

        new_strategy = strategy.model_copy(update={
            "available_cash": snapshot["available_cash"],
            "positions": positions,
            "updated_at": _now_iso(),
        })
        self._persist(new_strategy)

    def reconcile_position(self, strategy_id: str, stock_code: str,
                           direction: str, requested_qty: int,
                           filled_qty: int, filled_price: float,
                           snapshot: Optional[dict]):
        """实际成交与委托不一致时，先解冻再按实际成交修正持仓。"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return

        if filled_qty <= 0:
            self.rollback_position(strategy_id, snapshot)
            return

        # 先回滚到委托前快照（完全解冻）
        self.rollback_position(strategy_id, snapshot)

        # 再按真实成交数量更新持仓
        strategy = self._repo.get_by_id(strategy_id)
        new_positions, new_cash = self._apply_actual_fill(
            strategy.positions,
            strategy.available_cash,
            stock_code,
            direction,
            filled_qty,
            filled_price,
        )
        new_strategy = strategy.model_copy(update={
            "available_cash": new_cash,
            "positions": new_positions,
            "updated_at": _now_iso(),
        })
        self._persist(new_strategy)

    @staticmethod
    def _apply_actual_fill(
        positions: List[dict],
        available_cash: float,
        stock_code: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> tuple:
        """按真实成交更新持仓。买入增加总数量和可用数量，卖出减少。"""
        cost = quantity * price
        positions = [dict(p) for p in positions]
        new_cash = available_cash

        if direction == "buy":
            new_cash -= cost
            found = False
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    total_qty = pos["quantity"] + quantity
                    total_cost = pos["avg_cost"] * pos["quantity"] + cost
                    pos["quantity"] = total_qty
                    pos["available_quantity"] = pos.get("available_quantity", 0) + quantity
                    pos["avg_cost"] = round(total_cost / total_qty, 4) if total_qty > 0 else 0
                    found = True
                    break
            if not found:
                positions.append(_make_position(
                    stock_code=stock_code,
                    stock_name="",
                    quantity=quantity,
                    avg_cost=price,
                ))
        elif direction == "sell":
            new_cash += cost
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    pos["quantity"] -= quantity
                    pos["available_quantity"] = pos.get("available_quantity", 0) - quantity
                    if pos["quantity"] <= 0:
                        positions = [p for p in positions if p["stock_code"] != stock_code]
                    break

        return positions, new_cash

    @staticmethod
    def _freeze_position(
        positions: List[dict],
        available_cash: float,
        stock_code: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> tuple:
        """下单时冻结待成交数量。总数量不变，可用数量减少，冻结数量增加。"""
        cost = quantity * price
        positions = [dict(p) for p in positions]
        new_cash = available_cash

        if direction == "buy":
            new_cash -= cost
            found = False
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    pos["available_quantity"] = max(
                        0, pos.get("available_quantity", 0) - quantity
                    )
                    pos["frozen_quantity"] = pos.get("frozen_quantity", 0) + quantity
                    found = True
                    break
            if not found:
                # 买入新股票但尚未成交：总数量为 0，全部冻结
                positions.append(_make_position(
                    stock_code=stock_code,
                    stock_name="",
                    quantity=0,
                    avg_cost=price,
                    available_quantity=0,
                    frozen_quantity=quantity,
                ))
        elif direction == "sell":
            new_cash += cost
            for pos in positions:
                if pos["stock_code"] == stock_code:
                    pos["available_quantity"] = max(
                        0, pos.get("available_quantity", 0) - quantity
                    )
                    pos["frozen_quantity"] = pos.get("frozen_quantity", 0) + quantity
                    break

        return positions, new_cash

    def _rebuild_positions(self, current_positions: List[dict], positions_value: List[dict], available_cash: float) -> tuple:
        """根据更新请求重建持仓列表，返回 (new_positions, new_cash)。"""
        codes = set(pa["stock_code"] for pa in positions_value)
        codes.update(pos["stock_code"] for pos in current_positions)
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
        for pos in current_positions:
            code = pos["stock_code"]
            if code in new_by_code:
                old_qty = pos["quantity"]
                old_avg = pos["avg_cost"]
                new_pos = new_by_code[code]
                new_qty = new_pos["quantity"]
                open_price = open_prices.get(code) or new_pos["avg_cost"]

                if new_qty > old_qty:
                    new_pos["avg_cost"] = round(
                        (old_qty * old_avg + (new_qty - old_qty) * open_price) / new_qty, 4
                    )
                else:
                    new_pos["avg_cost"] = old_avg

                old_cost = old_qty * old_avg
                new_cost = new_pos["avg_cost"] * new_qty
                available_cash += (old_cost - new_cost)
                kept.append(new_pos)
                del new_by_code[code]
            else:
                available_cash += pos["avg_cost"] * pos["quantity"]

        for new_pos in new_by_code.values():
            open_price = open_prices.get(new_pos["stock_code"]) or new_pos["avg_cost"]
            new_pos["avg_cost"] = open_price
            available_cash -= open_price * new_pos["quantity"]
            kept.append(new_pos)

        if available_cash < 0:
            raise ValueError("可用资金不足，无法完成持仓分配")

        # 重建后的持仓默认可用数量等于总数量，冻结为 0
        result = [
            _make_position(
                stock_code=p["stock_code"],
                stock_name=p.get("stock_name", ""),
                quantity=p["quantity"],
                avg_cost=p["avg_cost"],
            )
            for p in kept
        ]
        return result, available_cash

    def add_trading_record(self, strategy_id: str, record: dict):
        """添加买卖记录"""
        strategy = self._repo.get_by_id(strategy_id)
        if not strategy:
            return
        records = list(strategy.trading_records)
        records.append(record)
        new_strategy = strategy.model_copy(update={
            "trading_records": records,
            "updated_at": _now_iso(),
        })
        self._persist(new_strategy)

    def list_all_enriched(self, trader, account) -> List[dict]:
        """列出所有策略，并用 QMT 实时行情数据富化持仓（current_price/market_value/daily_pnl）。"""
        self._refresh_cache()
        if not self._strategies:
            return []

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

        all_codes = {pos["stock_code"] for s in self._strategies.values() for pos in s.positions if pos["stock_code"]}
        preclose_map = fetch_preclose_from_xtdata(all_codes)

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

            daily_pnl_total = 0.0
            enriched_positions = []
            for pos in s.positions:
                code = pos["stock_code"]
                enriched = dict(pos)

                qty = pos["quantity"]
                qmt_data = qmt_index.get(code)
                qmt_vol = qmt_data["volume"] if qmt_data else 0

                if qmt_data and qmt_data["current_price"] > 0:
                    enriched["current_price"] = qmt_data["current_price"]
                else:
                    enriched["current_price"] = 0.0

                if qmt_data and qmt_vol > 0:
                    ratio = qty / qmt_vol
                    enriched["market_value"] = round(qmt_data["market_value"] * ratio, 2)
                else:
                    enriched["market_value"] = round(enriched["current_price"] * qty, 2)

                preclose = preclose_map.get(code)
                mv = enriched["market_value"]
                if preclose is not None and preclose > 0 and qty > 0:
                    pos_daily_pnl = round(mv - preclose * qty, 2)
                else:
                    pos_daily_pnl = 0.0
                enriched["daily_pnl"] = pos_daily_pnl
                daily_pnl_total += pos_daily_pnl

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

    def _persist(self, strategy: Strategy) -> Strategy:
        """保存策略并同步内存缓存。"""
        saved = self._repo.save(strategy)
        self._strategies[saved.id] = saved
        return saved

    def _refresh_cache(self):
        """从 Repository 刷新内存缓存。"""
        self._strategies = {
            s.id: s for s in self._repo.list_all(include_disabled=True)
        }
