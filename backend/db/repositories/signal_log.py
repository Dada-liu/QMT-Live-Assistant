"""信号日志 Repository。"""
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.db.models.signal_log import SignalLogModel
from backend.db.repositories.base import Repository, InMemoryRepository
from backend.db.base import synchronized


class SignalLogRepository(Repository[SignalLogModel]):
    """信号日志 Repository 接口。"""

    def update_processed_order(self, signal_log_id: str, order_id: Optional[str]) -> None: ...

    def update_error(self, signal_log_id: str, error_msg: str) -> None: ...


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """将 naive datetime 统一视为 UTC 并附加时区信息。"""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class InMemorySignalLogRepository(InMemoryRepository[SignalLogModel], SignalLogRepository):
    """内存信号日志 Repository。"""

    def update_processed_order(self, signal_log_id: str, order_id: Optional[str]) -> None:
        log = self._store.get(signal_log_id)
        if log is not None:
            log.processed_order_id = order_id

    def update_error(self, signal_log_id: str, error_msg: str) -> None:
        log = self._store.get(signal_log_id)
        if log is not None:
            log.error_msg = error_msg


class SQLAlchemySignalLogRepository(SignalLogRepository):
    """SQLAlchemy 信号日志 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    @synchronized
    def add(self, entity: SignalLogModel) -> SignalLogModel:
        try:
            self._session.add(entity)
            self._session.commit()
            self._session.refresh(entity)
            return self._attach_tz(entity)
        except Exception:
            self._session.rollback()
            raise

    @synchronized
    def get(self, id: str) -> Optional[SignalLogModel]:
        entity = self._session.get(SignalLogModel, id)
        return self._attach_tz(entity) if entity else None

    @synchronized
    def update(self, entity: SignalLogModel) -> SignalLogModel:
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
    def list_all(self, **filters) -> List[SignalLogModel]:
        query = self._session.query(SignalLogModel)
        for key, value in filters.items():
            if hasattr(SignalLogModel, key) and value is not None:
                query = query.filter(getattr(SignalLogModel, key) == value)
        return [self._attach_tz(entity) for entity in query.all()]

    @synchronized
    def update_processed_order(self, signal_log_id: str, order_id: Optional[str]) -> None:
        log = self.get(id=signal_log_id)
        if log is not None:
            try:
                log.processed_order_id = order_id
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

    @synchronized
    def update_error(self, signal_log_id: str, error_msg: str) -> None:
        log = self.get(id=signal_log_id)
        if log is not None:
            try:
                log.error_msg = error_msg
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

    @staticmethod
    def _attach_tz(entity: SignalLogModel) -> SignalLogModel:
        """确保从数据库读取的时间字段携带 UTC 时区。"""
        entity.received_at = _ensure_utc(entity.received_at)
        entity.created_at = _ensure_utc(entity.created_at)
        return entity
