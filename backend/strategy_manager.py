"""策略管理器。

管理多个远程交易策略，支持策略 CRUD、资金分配、持仓跟踪、
交易记录，以及基于 QMT 实时行情的持仓富化和当日盈亏计算。
"""
import copy
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from backend.utils import (
    fetch_preclose_from_xtdata,
    fetch_open_prices_from_xtdata,
    fetch_stock_names_from_xtdata,
    validate_security_type_for_strategy,
    validate_market_price_type_for_security_type,
)
from backend.db.base import db_lock
from backend.db.repositories.strategy import StrategyRepository, InMemoryStrategyRepository
from backend.models.strategy import Strategy, StrategyCreate, StrategyUpdate, PositionAssignment


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_position(stock_code: str, stock_name: str, quantity: int, avg_cost: float,
                   available_quantity: Optional[int] = None,
                   frozen_quantity: int = 0,
                   yesterday_quantity: int = 0,
                   yesterday_close: float = 0.0,
                   today_bought_quantity: int = 0,
                   today_bought_cost: float = 0.0) -> dict:
    """构造标准化持仓字典。"""
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "quantity": quantity,
        "available_quantity": available_quantity if available_quantity is not None else quantity,
        "frozen_quantity": frozen_quantity,
        "avg_cost": avg_cost,
        "yesterday_quantity": yesterday_quantity,
        "yesterday_close": yesterday_close,
        "today_bought_quantity": today_bought_quantity,
        "today_bought_cost": today_bought_cost,
    }


class StrategyManager:
    """策略管理器 — 管理所有策略的生命周期和资金持仓跟踪"""

    ENRICHED_CACHE_TTL = 2.0
    """list_all_enriched 富化结果的缓存秒数；类属性便于测试 monkeypatch。"""

    def __init__(self, repository: Optional[StrategyRepository] = None):
        self._repo = repository or InMemoryStrategyRepository()
        self._daily_profit: float = 0.0
        self._strategies: Dict[str, Strategy] = {}
        self._data_version = 0
        self._enriched_lock = threading.Lock()
        self._enriched_cache: Optional[List[dict]] = None
        self._enriched_cache_time: float = 0.0
        self._enriched_cache_version: int = -1
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
            insufficient_funds_policy=data.insufficient_funds_policy,
            defer_buy_on_insufficient_funds=data.defer_buy_on_insufficient_funds,
            bark_notify_enabled=data.bark_notify_enabled,
            default_market_price_type=data.default_market_price_type,
            security_type=data.security_type,
        )
        validate_market_price_type_for_security_type(
            data.security_type, data.default_market_price_type
        )
        if data.positions:
            for pa in data.positions:
                validate_security_type_for_strategy(data.security_type, pa.stock_code)
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
                    today_bought_quantity=pa.quantity,
                    today_bought_cost=round(cost, 4),
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

    def get_position(self, strategy_id: str, stock_code: str) -> Optional[dict]:
        """获取策略下某只股票的持仓字典（只读）。"""
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            return None
        return next(
            (p for p in strategy.positions if p["stock_code"] == stock_code), None
        )

    def get_quantity(self, strategy_id: str, stock_code: str) -> int:
        """获取策略下某只股票的总持仓数量。"""
        pos = self.get_position(strategy_id, stock_code)
        return pos["quantity"] if pos else 0

    def get_available_quantity(self, strategy_id: str, stock_code: str) -> int:
        """获取策略下某只股票的可用持仓数量。"""
        pos = self.get_position(strategy_id, stock_code)
        return pos.get("available_quantity", 0) if pos else 0

    def get_available_cash(self, strategy_id: str) -> float:
        """获取策略可用资金。"""
        strategy = self._strategies.get(strategy_id)
        return strategy.available_cash if strategy else 0.0

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
            # 校验：修改后的分配资金不能低于现有持仓总成本
            current_positions_cost = sum(
                p["avg_cost"] * p["quantity"] for p in strategy.positions
            )
            if update_data["allocated_funds"] < current_positions_cost:
                raise ValueError(
                    f"修改后的分配资金({update_data['allocated_funds']:.2f})"
                    f"低于现有持仓成本({current_positions_cost:.2f})，无法修改"
                )
            diff = update_data["allocated_funds"] - strategy.allocated_funds
            update_data["available_cash"] = strategy.available_cash + diff

        update_data["updated_at"] = _now_iso()

        effective_security_type = update_data.get("security_type", strategy.security_type)
        effective_market_price_type = update_data.get(
            "default_market_price_type", strategy.default_market_price_type
        )
        validate_market_price_type_for_security_type(
            effective_security_type, effective_market_price_type
        )

        if "security_type" in update_data and positions_value is None:
            # 仅修改策略种类时，存量持仓必须与新券种相容（否则存量持仓将无法卖出）
            for pos in strategy.positions:
                validate_security_type_for_strategy(
                    update_data["security_type"], pos["stock_code"]
                )

        if positions_value is not None:
            # 持仓分配按"生效后的策略种类"校验券种一致性
            effective_security_type = update_data.get("security_type", strategy.security_type)
            for pa in positions_value:
                validate_security_type_for_strategy(
                    effective_security_type, pa["stock_code"]
                )
            base_cash = update_data.get("available_cash", strategy.available_cash)
            new_positions, new_cash = self._rebuild_positions(
                strategy.positions, positions_value, base_cash
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
            self._data_version += 1
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
        with db_lock:
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
        """下单时乐观更新策略持仓/资金，并返回本订单的增量快照。

        买入：未成交前只冻结资金，不创建/修改 position 行。
        卖出：减少可用数量、增加冻结数量、增加预期资金；可用数量不足时返回 None。

        返回的 snapshot 包含本订单造成的增量（delta_*），多笔同股票订单并发
        时 rollback / reconcile 只撤销本订单的增量，不影响其他待成交订单。
        """
        with db_lock:
            strategy = self._repo.get_by_id(strategy_id)
            if not strategy:
                return None

            old_pos = next(
                (p for p in strategy.positions if p["stock_code"] == stock_code), None
            )
            pre_quantity = old_pos["quantity"] if old_pos else 0
            pre_available = old_pos["available_quantity"] if old_pos else 0
            pre_frozen = old_pos["frozen_quantity"] if old_pos else 0
            pre_avg_cost = old_pos["avg_cost"] if old_pos else 0.0
            pre_cash = strategy.available_cash

            freeze_result = self._freeze_position(
                strategy.positions,
                strategy.available_cash,
                stock_code,
                direction,
                quantity,
                price,
            )
            if freeze_result is None:
                return None
            new_positions, new_cash = freeze_result

            new_pos = next(
                (p for p in new_positions if p["stock_code"] == stock_code), None
            )
            post_available = new_pos["available_quantity"] if new_pos else pre_available
            post_frozen = new_pos["frozen_quantity"] if new_pos else pre_frozen

            snapshot = {
                "stock_code": stock_code,
                "direction": direction,
                "requested_quantity": quantity,
                "price": price,
                # 冻结前状态（保留以兼容现有测试与调试）
                "quantity": pre_quantity,
                "available_quantity": pre_available,
                "frozen_quantity": pre_frozen,
                "avg_cost": pre_avg_cost,
                "available_cash": pre_cash,
                # 本订单造成的增量
                "delta_available_quantity": post_available - pre_available,
                "delta_frozen_quantity": post_frozen - pre_frozen,
                "delta_cash": new_cash - pre_cash,
            }

            new_strategy = strategy.model_copy(update={
                "positions": new_positions,
                "available_cash": new_cash,
                "updated_at": _now_iso(),
            })
            self._persist(new_strategy)
            return snapshot

    @staticmethod
    def _rollback_position_deltas(positions: List[dict], stock_code: str,
                                   delta_available: int, delta_frozen: int) -> List[dict]:
        """仅撤销指定订单的冻结增量，保留其他订单的冻结状态。"""
        result = []
        for pos in positions:
            if pos["stock_code"] != stock_code:
                result.append(dict(pos))
                continue

            new_pos = dict(pos)
            new_pos["available_quantity"] = (
                new_pos.get("available_quantity", 0) - delta_available
            )
            new_pos["frozen_quantity"] = max(
                0, new_pos.get("frozen_quantity", 0) - delta_frozen
            )
            # 维持 invariant：可用数量 = 总数量 - 冻结数量
            new_pos["available_quantity"] = (
                new_pos["quantity"] - new_pos["frozen_quantity"]
            )

            if (new_pos.get("quantity", 0) == 0 and
                    new_pos.get("available_quantity", 0) == 0 and
                    new_pos.get("frozen_quantity", 0) == 0):
                continue

            result.append(new_pos)
        return result

    def rollback_position(self, strategy_id: str, snapshot: Optional[dict]):
        """根据增量快照撤销乐观持仓更新（解冻）。

        卖单已增量结算（settled_quantity>0）时，只释放未成交部分的冻结，
        已成交部分的持仓扣减与回款入账保留。
        """
        with db_lock:
            strategy = self._repo.get_by_id(strategy_id)
            if not strategy or not snapshot:
                return

            delta_frozen = snapshot.get("delta_frozen_quantity", 0)
            delta_available = snapshot.get("delta_available_quantity", 0)
            settled = int(snapshot.get("settled_quantity", 0) or 0)
            if settled > 0:
                # 增量成交时已按成交量扣减冻结，这里只回滚剩余未成交部分
                residual = max(0, delta_frozen - settled)
                delta_frozen = residual
                delta_available = -residual if delta_available < 0 else delta_available

            new_positions = self._rollback_position_deltas(
                strategy.positions,
                snapshot["stock_code"],
                delta_available,
                delta_frozen,
            )
            new_cash = strategy.available_cash - snapshot.get("delta_cash", 0.0)

            new_strategy = strategy.model_copy(update={
                "available_cash": new_cash,
                "positions": new_positions,
                "updated_at": _now_iso(),
            })
            self._persist(new_strategy)

    def settle_partial_sell(self, strategy_id: str, stock_code: str,
                            delta_qty: int, delta_price: float,
                            snapshot: Optional[dict]):
        """卖单部分成交时把该笔回款立即入账（增量结算）。

        复用 _apply_actual_fill 入账回款并按 FIFO 扣减持仓，再显式扣减冻结量，
        维持 available = quantity - frozen（增量成交双边同减，可用数量不变）；
        snapshot 累加 settled_quantity，终态 reconcile / rollback 只补差未结算部分。
        """
        if delta_qty <= 0 or snapshot is None:
            return
        with db_lock:
            strategy = self._repo.get_by_id(strategy_id)
            if not strategy:
                return

            new_positions, new_cash = self._apply_actual_fill(
                strategy.positions,
                strategy.available_cash,
                stock_code,
                "sell",
                delta_qty,
                delta_price,
            )
            # _apply_actual_fill 不动冻结量，这里显式扣减本笔成交占用的冻结
            adjusted_positions = []
            for pos in new_positions:
                if pos["stock_code"] != stock_code:
                    adjusted_positions.append(pos)
                    continue
                new_pos = dict(pos)
                new_pos["frozen_quantity"] = max(
                    0, new_pos.get("frozen_quantity", 0) - delta_qty
                )
                new_pos["available_quantity"] = max(
                    0, new_pos["quantity"] - new_pos["frozen_quantity"]
                )
                adjusted_positions.append(new_pos)

            snapshot["settled_quantity"] = int(snapshot.get("settled_quantity", 0) or 0) + delta_qty

            new_strategy = strategy.model_copy(update={
                "available_cash": new_cash,
                "positions": adjusted_positions,
                "updated_at": _now_iso(),
            })
            self._persist(new_strategy)

    def reconcile_position(self, strategy_id: str, stock_code: str,
                           direction: str, requested_qty: int,
                           filled_qty: int, filled_price: float,
                           snapshot: Optional[dict]):
        """实际成交与委托不一致时，先解冻再按实际成交修正持仓。

        卖单部分成交已增量结算（settled_quantity>0）时走补差模式：
        rollback 只释放未成交部分的冻结，_apply_actual_fill 只入账
        未被增量回调覆盖的成交量；买单 settled=0 时退化为原有行为。
        """
        with db_lock:
            strategy = self._repo.get_by_id(strategy_id)
            if not strategy:
                return

            if filled_qty <= 0:
                self.rollback_position(strategy_id, snapshot)
                return

            settled = int(snapshot.get("settled_quantity", 0) or 0) if snapshot else 0
            unsettled_filled = filled_qty - settled if direction == "sell" else filled_qty

            # 先回滚本订单的乐观冻结（rollback 内部已感知 settled，只释放未结算部分）
            self.rollback_position(strategy_id, snapshot)

            if unsettled_filled <= 0:
                # 卖单成交已全部增量入账，无需重复修正
                return

            # 再按真实成交数量更新持仓
            strategy = self._repo.get_by_id(strategy_id)
            new_positions, new_cash = self._apply_actual_fill(
                strategy.positions,
                strategy.available_cash,
                stock_code,
                direction,
                unsettled_filled,
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
        """按真实成交更新持仓，并维持 available_quantity = quantity - frozen_quantity。"""
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
                    pos["avg_cost"] = round(total_cost / total_qty, 4) if total_qty > 0 else 0
                    pos["available_quantity"] = (
                        pos["quantity"] - pos.get("frozen_quantity", 0)
                    )
                    pos["today_bought_quantity"] = pos.get("today_bought_quantity", 0) + quantity
                    pos["today_bought_cost"] = round(
                        pos.get("today_bought_cost", 0.0) + cost, 4
                    )
                    found = True
                    break
            if not found:
                name_map = fetch_stock_names_from_xtdata({stock_code})
                stock_name = name_map.get(stock_code) or ""
                positions.append(_make_position(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    quantity=quantity,
                    avg_cost=price,
                    today_bought_quantity=quantity,
                    today_bought_cost=round(cost, 4),
                ))
        elif direction == "sell":
            new_cash += cost
            new_positions = []
            for pos in positions:
                if pos["stock_code"] != stock_code:
                    new_positions.append(pos)
                    continue

                new_pos = dict(pos)
                remaining = quantity

                # 先进先出：先扣减昨日持仓
                yest_qty = new_pos.get("yesterday_quantity", 0)
                if yest_qty > 0:
                    deduct = min(remaining, yest_qty)
                    new_pos["yesterday_quantity"] = yest_qty - deduct
                    remaining -= deduct

                # 再扣减今日买入持仓
                if remaining > 0:
                    today_qty = new_pos.get("today_bought_quantity", 0)
                    today_cost = new_pos.get("today_bought_cost", 0.0)
                    deduct = min(remaining, today_qty)
                    avg_buy_price = (today_cost / today_qty) if today_qty > 0 else 0.0
                    new_pos["today_bought_quantity"] = today_qty - deduct
                    new_pos["today_bought_cost"] = round(
                        today_cost - deduct * avg_buy_price, 4
                    )
                    remaining -= deduct

                new_pos["quantity"] = max(0, pos["quantity"] - quantity)
                new_pos["available_quantity"] = max(
                    0, new_pos["quantity"] - new_pos.get("frozen_quantity", 0)
                )

                # 卖出后按剩余持仓的拆分成本重新计算 avg_cost
                if new_pos["quantity"] > 0:
                    remaining_cost = (
                        new_pos["yesterday_quantity"] * new_pos["yesterday_close"]
                        + new_pos["today_bought_cost"]
                    )
                    new_pos["avg_cost"] = round(
                        remaining_cost / new_pos["quantity"], 4
                    )
                else:
                    new_pos["avg_cost"] = 0.0

                if new_pos["quantity"] > 0:
                    new_positions.append(new_pos)
            positions = new_positions

        return positions, new_cash

    @staticmethod
    def _freeze_position(
        positions: List[dict],
        available_cash: float,
        stock_code: str,
        direction: str,
        quantity: int,
        price: float,
    ) -> Optional[tuple]:
        """下单时乐观冻结：买入只冻结资金；卖出冻结持仓可用数量。

        返回 (new_positions, new_cash)；买入资金不足或卖出可用数量不足时返回 None。
        """
        cost = quantity * price
        positions = [dict(p) for p in positions]
        new_cash = available_cash

        if direction == "buy":
            if cost > available_cash:
                return None
            new_cash -= cost
            # 买入未成交前不创建/修改 position 行，仅冻结资金
        elif direction == "sell":
            pos = next(
                (p for p in positions if p["stock_code"] == stock_code), None
            )
            if pos is None:
                return None
            available = pos.get("available_quantity", pos.get("quantity", 0))
            if available < quantity:
                return None

            # 卖出未成交前仅冻结持仓，不提前增加资金；资金在成交后由 _apply_actual_fill 处理
            pos["frozen_quantity"] = pos.get("frozen_quantity", 0) + quantity
            pos["available_quantity"] = pos["quantity"] - pos["frozen_quantity"]

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
            cost = pa["quantity"] * open_price
            new_by_code[code] = {
                "stock_code": code,
                "stock_name": pa.get("stock_name", ""),
                "quantity": pa["quantity"],
                "avg_cost": open_price,
                "yesterday_quantity": 0,
                "yesterday_close": 0.0,
                "today_bought_quantity": pa["quantity"],
                "today_bought_cost": round(cost, 4),
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
        # today_bought_cost 与最终 avg_cost 保持一致
        result = [
            _make_position(
                stock_code=p["stock_code"],
                stock_name=p.get("stock_name", ""),
                quantity=p["quantity"],
                avg_cost=p["avg_cost"],
                yesterday_quantity=p.get("yesterday_quantity", 0),
                yesterday_close=p.get("yesterday_close", 0.0),
                today_bought_quantity=p.get("today_bought_quantity", 0),
                today_bought_cost=round(p["quantity"] * p["avg_cost"], 4),
            )
            for p in kept
        ]
        return result, available_cash

    def add_trading_record(self, strategy_id: str, record: dict):
        """添加买卖记录"""
        with db_lock:
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

    def _current_trade_date(self) -> str:
        """返回当前本地日期 YYYYMMDD。未来可替换为交易日历。"""
        return datetime.now().strftime("%Y%m%d")

    def _rollover_positions_if_needed(self, strategies: Dict[str, Strategy]) -> Dict[str, Strategy]:
        """每日首次查询时自动检测日期，将 today_bought 合并到 yesterday。"""
        current_date = self._current_trade_date()
        result: Dict[str, Strategy] = {}
        for sid, strategy in strategies.items():
            if strategy.last_rollover_date == current_date:
                result[sid] = strategy
                continue

            codes = {p["stock_code"] for p in strategy.positions if p.get("stock_code")}
            preclose_map = fetch_preclose_from_xtdata(codes)

            new_positions = []
            for pos in strategy.positions:
                code = pos["stock_code"]
                qty = pos.get("quantity", 0)
                preclose = preclose_map.get(code)
                fallback_close = pos.get("avg_cost", 0.0)
                yesterday_close = preclose if preclose is not None and preclose > 0 else fallback_close

                new_pos = dict(pos)
                new_pos["yesterday_quantity"] = qty
                new_pos["yesterday_close"] = round(yesterday_close, 4)
                new_pos["today_bought_quantity"] = 0
                new_pos["today_bought_cost"] = 0.0
                new_positions.append(new_pos)

            new_strategy = strategy.model_copy(deep=True, update={
                "positions": new_positions,
                "last_rollover_date": current_date,
                "updated_at": _now_iso(),
            })
            new_strategy = self._persist(new_strategy)
            result[sid] = new_strategy
        return result

    def list_all_enriched(self, trader, account, force_refresh: bool = False) -> List[dict]:
        """列出所有策略，并用 QMT 实时行情数据富化持仓（current_price/market_value/daily_pnl）。

        多平台并发轮询时共享同一份结果：锁保证同一时刻只有一个请求真正
        查询 QMT（单飞），其余请求在 TTL 内直接读缓存；策略数据变更
        （_persist/delete）会递增 _data_version 使缓存立即失效。
        返回深拷贝，调用方对结果字典的修改不会污染缓存。
        """
        with self._enriched_lock:
            now = time.monotonic()
            if (not force_refresh
                    and self._enriched_cache is not None
                    and self._enriched_cache_version == self._data_version
                    and now - self._enriched_cache_time < self.ENRICHED_CACHE_TTL):
                return copy.deepcopy(self._enriched_cache)
            result = self._list_all_enriched_uncached(trader, account)
            self._enriched_cache = result
            self._enriched_cache_time = time.monotonic()
            self._enriched_cache_version = self._data_version
            return copy.deepcopy(result)

    def _list_all_enriched_uncached(self, trader, account) -> List[dict]:
        self._refresh_cache()
        if not self._strategies:
            return []

        # 每日首次查询时自动跨日合并
        self._strategies = self._rollover_positions_if_needed(self._strategies)

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

                yest_qty = pos.get("yesterday_quantity", 0)
                yest_close = pos.get("yesterday_close", 0.0)
                today_qty = pos.get("today_bought_quantity", 0)
                today_cost = pos.get("today_bought_cost", 0.0)
                current_price = enriched["current_price"]

                pos_daily_pnl = 0.0
                if current_price > 0:
                    if yest_qty > 0 and yest_close > 0:
                        pos_daily_pnl += current_price * yest_qty - yest_close * yest_qty
                    if today_qty > 0 and today_cost > 0:
                        pos_daily_pnl += current_price * today_qty - today_cost
                enriched["daily_pnl"] = round(pos_daily_pnl, 2)
                daily_pnl_total += pos_daily_pnl

                avg_cost = pos.get("avg_cost", 0)
                enriched["total_pnl"] = round(enriched["market_value"] - avg_cost * qty, 2) if qty > 0 else 0.0

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
        self._data_version += 1
        return saved

    def _refresh_cache(self):
        """从 Repository 刷新内存缓存。"""
        self._strategies = {
            s.id: s for s in self._repo.list_all(include_disabled=True)
        }
