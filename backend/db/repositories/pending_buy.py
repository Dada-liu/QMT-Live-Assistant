"""挂起买单 Repository。"""
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.db.models.pending_buy_order import PendingBuyOrderModel, PENDING_BUY_WAITING
from backend.db.repositories.base import Repository, InMemoryRepository
from backend.db.base import synchronized


class PendingBuyRepository(Repository[PendingBuyOrderModel]):
    """挂起买单 Repository 接口。"""

    def list_waiting(self) -> List[PendingBuyOrderModel]: ...


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """将 naive datetime 统一视为 UTC 并附加时区信息。"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class InMemoryPendingBuyRepository(InMemoryRepository[PendingBuyOrderModel], PendingBuyRepository):
    """内存挂起买单 Repository。"""

    def list_waiting(self) -> List[PendingBuyOrderModel]:
        waiting = [e for e in self._store.values() if e.status == PENDING_BUY_WAITING]
        return sorted(waiting, key=lambda e: e.created_at)


class SQLAlchemyPendingBuyRepository(PendingBuyRepository):
    """SQLAlchemy 挂起买单 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    @synchronized
    def add(self, entity: PendingBuyOrderModel) -> PendingBuyOrderModel:
        try:
            self._session.add(entity)
            self._session.commit()
            self._session.refresh(entity)
            return self._attach_tz(entity)
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def get(self, id: str) -> Optional[PendingBuyOrderModel]:
        entity = self._session.get(PendingBuyOrderModel, id)
        return self._attach_tz(entity) if entity else None

    @synchronized
    def update(self, entity: PendingBuyOrderModel) -> PendingBuyOrderModel:
        try:
            self._session.commit()
            self._session.refresh(entity)
            return self._attach_tz(entity)
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def delete(self, id: str) -> bool:
        obj = self.get(id)
        if obj is None:
            return False
        try:
            self._session.delete(obj)
            self._session.commit()
            return True
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def list_all(self, **filters) -> List[PendingBuyOrderModel]:
        query = self._session.query(PendingBuyOrderModel)
        for key, value in filters.items():
            if hasattr(PendingBuyOrderModel, key) and value is not None:
                query = query.filter(getattr(PendingBuyOrderModel, key) == value)
        return [self._attach_tz(entity) for entity in query.all()]

    @synchronized
    def list_waiting(self) -> List[PendingBuyOrderModel]:
        rows = (
            self._session.query(PendingBuyOrderModel)
            .filter_by(status=PENDING_BUY_WAITING)
            .order_by(PendingBuyOrderModel.created_at.asc())
            .all()
        )
        return [self._attach_tz(entity) for entity in rows]

    @staticmethod
    def _attach_tz(entity: PendingBuyOrderModel) -> PendingBuyOrderModel:
        """确保从数据库读取的时间字段携带 UTC 时区。"""
        entity.created_at = _ensure_utc(entity.created_at)
        entity.expire_at = _ensure_utc(entity.expire_at)
        entity.resolved_at = _ensure_utc(entity.resolved_at)
        return entity
