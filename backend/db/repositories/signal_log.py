"""信号日志 Repository。"""
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.db.models.signal_log import SignalLogModel
from backend.db.repositories.base import Repository, InMemoryRepository


class SignalLogRepository(Repository[SignalLogModel]):
    """信号日志 Repository 接口。"""

    def update_processed_order(self, signal_log_id: str, order_id: Optional[str]) -> None: ...

    def update_error(self, signal_log_id: str, error_msg: str) -> None: ...


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

    def add(self, entity: SignalLogModel) -> SignalLogModel:
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get(self, id: str) -> Optional[SignalLogModel]:
        return self._session.get(SignalLogModel, id)

    def update(self, entity: SignalLogModel) -> SignalLogModel:
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def delete(self, id: str) -> bool:
        obj = self.get(id)
        if obj is None:
            return False
        self._session.delete(obj)
        self._session.commit()
        return True

    def list_all(self, **filters) -> List[SignalLogModel]:
        query = self._session.query(SignalLogModel)
        for key, value in filters.items():
            if hasattr(SignalLogModel, key) and value is not None:
                query = query.filter(getattr(SignalLogModel, key) == value)
        return query.all()

    def update_processed_order(self, signal_log_id: str, order_id: Optional[str]) -> None:
        log = self.get(signal_log_id)
        if log is not None:
            log.processed_order_id = order_id
            self._session.commit()

    def update_error(self, signal_log_id: str, error_msg: str) -> None:
        log = self.get(signal_log_id)
        if log is not None:
            log.error_msg = error_msg
            self._session.commit()
