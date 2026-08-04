"""策略 Repository 接口与实现。"""
from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.constants import INSUFFICIENT_FUNDS_REJECT
from backend.models.strategy import Strategy
from backend.db.models.strategy import StrategyModel
from backend.db.models.position import PositionModel
from backend.db.models.strategy_token import StrategyTokenModel
from backend.db.base import synchronized


def _token_prefix(token: str) -> str:
    return token[:8]


class StrategyRepository(ABC):
    """策略数据访问抽象。"""

    @abstractmethod
    def get_by_id(self, strategy_id: str) -> Optional[Strategy]: ...

    @abstractmethod
    def get_by_token(self, token: str) -> Optional[Strategy]: ...

    @abstractmethod
    def list_all(self, include_disabled: bool = False, include_deleted: bool = False) -> List[Strategy]: ...

    @abstractmethod
    def save(self, strategy: Strategy) -> Strategy: ...

    @abstractmethod
    def delete(self, strategy_id: str) -> bool: ...


class InMemoryStrategyRepository(StrategyRepository):
    """内存策略 Repository，用于测试和无持久化场景。"""

    def __init__(self):
        self._store: dict[str, Strategy] = {}
        self._token_index: dict[str, str] = {}

    def get_by_id(self, strategy_id: str) -> Optional[Strategy]:
        strategy = self._store.get(strategy_id)
        if strategy is None:
            return None
        return strategy.model_copy(deep=True)

    def get_by_token(self, token: str) -> Optional[Strategy]:
        strategy_id = self._token_index.get(token)
        if not strategy_id:
            return None
        return self.get_by_id(strategy_id)

    def list_all(self, include_disabled: bool = False, include_deleted: bool = False) -> List[Strategy]:
        return [
            s.model_copy(deep=True)
            for s in self._store.values()
            if (include_disabled or s.enabled)
            and (include_deleted or s.deleted_at is None)
        ]

    def save(self, strategy: Strategy) -> Strategy:
        copied = strategy.model_copy(deep=True)
        self._store[copied.id] = copied
        self._token_index[copied.token] = copied.id
        return copied.model_copy(deep=True)

    def delete(self, strategy_id: str) -> bool:
        strategy = self._store.pop(strategy_id, None)
        if strategy is None:
            return False
        self._token_index = {
            t: sid for t, sid in self._token_index.items() if sid != strategy_id
        }
        return True


class SQLAlchemyStrategyRepository(StrategyRepository):
    """SQLAlchemy 策略 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    @synchronized
    def get_by_id(self, strategy_id: str) -> Optional[Strategy]:
        row = self._session.get(StrategyModel, strategy_id)
        if row is None or row.deleted_at is not None:
            return None
        return self._to_domain(row)

    @synchronized
    def get_by_token(self, token: str) -> Optional[Strategy]:
        token_row = (
            self._session.query(StrategyTokenModel)
            .filter_by(token=token, revoked_at=None)
            .order_by(StrategyTokenModel.created_at.desc())
            .first()
        )
        if token_row is None:
            return None
        return self.get_by_id(token_row.strategy_id)

    @synchronized
    def list_all(self, include_disabled: bool = False, include_deleted: bool = False) -> List[Strategy]:
        query = self._session.query(StrategyModel)
        if not include_deleted:
            query = query.filter(StrategyModel.deleted_at.is_(None))
        if not include_disabled:
            query = query.filter(StrategyModel.enabled.is_(True))
        return [self._to_domain(row) for row in query.all()]

    @synchronized
    def save(self, strategy: Strategy) -> Strategy:
        try:
            existing = self._session.get(StrategyModel, strategy.id)
            if existing is None:
                model = self._to_model(strategy)
                self._session.add(model)
                self._session.flush()
                self._session.refresh(model)
                saved_row = model
            else:
                self._update_model(existing, strategy)
                self._session.flush()
                self._session.refresh(existing)
                saved_row = existing
            self._session.commit()
            return self._to_domain(saved_row)
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def delete(self, strategy_id: str) -> bool:
        row = self._session.get(StrategyModel, strategy_id)
        if row is None or row.deleted_at is not None:
            return False
        row.deleted_at = datetime.now(timezone.utc)
        self._session.commit()
        return True

    def _to_domain(self, row: StrategyModel) -> Strategy:
        positions = [
            {
                "stock_code": p.stock_code,
                "stock_name": p.stock_name or "",
                "quantity": p.quantity,
                "available_quantity": p.available_quantity,
                "frozen_quantity": p.frozen_quantity,
                "avg_cost": float(p.avg_cost),
                "yesterday_quantity": p.yesterday_quantity,
                "yesterday_close": float(p.yesterday_close),
                "today_bought_quantity": p.today_bought_quantity,
                "today_bought_cost": float(p.today_bought_cost),
            }
            for p in row.positions
        ]
        return Strategy(
            id=row.id,
            name=row.name,
            description=row.description or "",
            enabled=row.enabled,
            token=self._resolve_token(row),
            allocated_funds=float(row.allocated_funds),
            available_cash=float(row.available_cash),
            insufficient_funds_policy=row.insufficient_funds_policy or INSUFFICIENT_FUNDS_REJECT,
            bark_notify_enabled=bool(row.bark_notify_enabled) if row.bark_notify_enabled is not None else True,
            default_market_price_type=row.default_market_price_type if row.default_market_price_type is not None else 5,
            total_asset=float(row.available_cash) + sum(
                p["avg_cost"] * p["quantity"] for p in positions
            ),
            daily_pnl=0.0,
            last_rollover_date=row.last_rollover_date,
            positions=positions,
            trading_records=list(row.trading_records or []),
            deleted_at=row.deleted_at.isoformat() if row.deleted_at else None,
            created_at=row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat(),
            updated_at=row.updated_at.isoformat() if row.updated_at else datetime.now(timezone.utc).isoformat(),
        )

    def _to_model(self, strategy: Strategy) -> StrategyModel:
        model = StrategyModel(
            id=strategy.id,
            account_id="",  # Phase 1 单账户，后续通过 account_id 关联
            name=strategy.name,
            description=strategy.description,
            enabled=strategy.enabled,
            allocated_funds=strategy.allocated_funds,
            available_cash=strategy.available_cash,
            insufficient_funds_policy=strategy.insufficient_funds_policy,
            bark_notify_enabled=strategy.bark_notify_enabled,
            default_market_price_type=strategy.default_market_price_type,
            trading_records=list(strategy.trading_records or []),
        )
        model.positions = self._positions_to_models(strategy)
        model.tokens = [self._token_to_model(strategy.id, strategy.token)]
        return model

    def _update_model(self, model: StrategyModel, strategy: Strategy) -> None:
        model.name = strategy.name
        model.description = strategy.description
        model.enabled = strategy.enabled
        model.allocated_funds = strategy.allocated_funds
        model.available_cash = strategy.available_cash
        model.insufficient_funds_policy = strategy.insufficient_funds_policy
        model.bark_notify_enabled = strategy.bark_notify_enabled
        model.default_market_price_type = strategy.default_market_price_type
        model.last_rollover_date = strategy.last_rollover_date
        model.trading_records = list(strategy.trading_records or [])
        model.updated_at = datetime.now(timezone.utc)

        # 同步 positions：删除旧记录，重建新记录
        for old_pos in list(model.positions):
            self._session.delete(old_pos)
        self._session.flush()
        model.positions = self._positions_to_models(strategy)

        # 同步 token：若不存在则新增
        existing_tokens = {t.token for t in model.tokens if t.revoked_at is None}
        if strategy.token not in existing_tokens:
            model.tokens.append(self._token_to_model(strategy.id, strategy.token))

    def _positions_to_models(self, strategy: Strategy) -> List[PositionModel]:
        seen = set()
        models = []
        for pos in (strategy.positions or []):
            code = pos.get("stock_code", "")
            if code in seen:
                continue
            seen.add(code)
            models.append(PositionModel(
                stock_code=code,
                stock_name=pos.get("stock_name", ""),
                quantity=pos.get("quantity", 0),
                available_quantity=pos.get("available_quantity", pos.get("quantity", 0)),
                frozen_quantity=pos.get("frozen_quantity", 0),
                avg_cost=pos.get("avg_cost", 0.0),
                yesterday_quantity=pos.get("yesterday_quantity", 0),
                yesterday_close=pos.get("yesterday_close", 0.0),
                today_bought_quantity=pos.get("today_bought_quantity", 0),
                today_bought_cost=pos.get("today_bought_cost", 0.0),
            ))
        return models

    @staticmethod
    def _token_to_model(strategy_id: str, token: str) -> StrategyTokenModel:
        return StrategyTokenModel(
            strategy_id=strategy_id,
            token=token,
            token_prefix=_token_prefix(token),
        )

    def _resolve_token(self, row: StrategyModel) -> str:
        """返回当前有效的完整 Token。"""
        active_token = next(
            (t for t in row.tokens if t.revoked_at is None),
            None,
        )
        return active_token.token if active_token else ""
