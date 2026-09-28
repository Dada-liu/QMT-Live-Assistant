"""资产快照 Repository。"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.db.models.asset_snapshot import AssetSnapshotModel
from backend.db.base import synchronized


class AssetSnapshotRepository(ABC):
    """资产快照数据访问抽象。"""

    @abstractmethod
    def upsert_snapshot(self, scope: str, strategy_id: Optional[str], ts: datetime,
                        total_asset: float, cash: float, market_value: float,
                        daily_pnl: float) -> AssetSnapshotModel: ...

    @abstractmethod
    def list_range(self, scope: str, strategy_id: Optional[str] = None,
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None) -> List[AssetSnapshotModel]: ...

    @abstractmethod
    def get_latest_before(self, scope: str, strategy_id: Optional[str],
                          ts: datetime) -> Optional[AssetSnapshotModel]: ...


class InMemoryAssetSnapshotRepository(AssetSnapshotRepository):
    """内存资产快照 Repository，用于测试和无持久化场景。"""

    def __init__(self):
        self._store: dict[tuple, AssetSnapshotModel] = {}

    def upsert_snapshot(self, scope: str, strategy_id: Optional[str], ts: datetime,
                        total_asset: float, cash: float, market_value: float,
                        daily_pnl: float) -> AssetSnapshotModel:
        key = (scope, strategy_id, ts)
        snapshot = self._store.get(key)
        if snapshot is None:
            snapshot = AssetSnapshotModel(scope=scope, strategy_id=strategy_id, ts=ts)
            self._store[key] = snapshot
        snapshot.total_asset = total_asset
        snapshot.cash = cash
        snapshot.market_value = market_value
        snapshot.daily_pnl = daily_pnl
        return snapshot

    def list_range(self, scope: str, strategy_id: Optional[str] = None,
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None) -> List[AssetSnapshotModel]:
        result = [
            s for s in self._store.values()
            if s.scope == scope and s.strategy_id == strategy_id
            and (start is None or s.ts >= start)
            and (end is None or s.ts <= end)
        ]
        result.sort(key=lambda s: s.ts)
        return result

    def get_latest_before(self, scope: str, strategy_id: Optional[str],
                          ts: datetime) -> Optional[AssetSnapshotModel]:
        candidates = [
            s for s in self._store.values()
            if s.scope == scope and s.strategy_id == strategy_id and s.ts < ts
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.ts)


class SQLAlchemyAssetSnapshotRepository(AssetSnapshotRepository):
    """SQLAlchemy 资产快照 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    def _scoped_query(self, scope: str, strategy_id: Optional[str]):
        query = self._session.query(AssetSnapshotModel).filter(
            AssetSnapshotModel.scope == scope
        )
        if strategy_id is None:
            query = query.filter(AssetSnapshotModel.strategy_id.is_(None))
        else:
            query = query.filter(AssetSnapshotModel.strategy_id == strategy_id)
        return query

    @synchronized
    def upsert_snapshot(self, scope: str, strategy_id: Optional[str], ts: datetime,
                        total_asset: float, cash: float, market_value: float,
                        daily_pnl: float) -> AssetSnapshotModel:
        try:
            snapshot = self._scoped_query(scope, strategy_id).filter(
                AssetSnapshotModel.ts == ts
            ).first()
            if snapshot is None:
                snapshot = AssetSnapshotModel(scope=scope, strategy_id=strategy_id, ts=ts)
                self._session.add(snapshot)
            snapshot.total_asset = total_asset
            snapshot.cash = cash
            snapshot.market_value = market_value
            snapshot.daily_pnl = daily_pnl
            self._session.commit()
            self._session.refresh(snapshot)
            return snapshot
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def list_range(self, scope: str, strategy_id: Optional[str] = None,
                   start: Optional[datetime] = None,
                   end: Optional[datetime] = None) -> List[AssetSnapshotModel]:
        query = self._scoped_query(scope, strategy_id)
        if start is not None:
            query = query.filter(AssetSnapshotModel.ts >= start)
        if end is not None:
            query = query.filter(AssetSnapshotModel.ts <= end)
        return query.order_by(AssetSnapshotModel.ts.asc()).all()

    @synchronized
    def get_latest_before(self, scope: str, strategy_id: Optional[str],
                          ts: datetime) -> Optional[AssetSnapshotModel]:
        return self._scoped_query(scope, strategy_id).filter(
            AssetSnapshotModel.ts < ts
        ).order_by(AssetSnapshotModel.ts.desc()).first()
