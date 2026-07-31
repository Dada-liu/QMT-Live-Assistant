"""应用设置 Repository 接口与实现（键值存储）。"""
from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.orm import Session
from backend.db.models.settings import AppSettingsModel


class SettingsRepository(ABC):
    """应用设置数据访问抽象。"""

    @abstractmethod
    def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...


class InMemorySettingsRepository(SettingsRepository):
    """内存设置 Repository，用于测试和无持久化场景。"""

    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    def set(self, key: str, value: str) -> None:
        self._store[key] = value


class SQLAlchemySettingsRepository(SettingsRepository):
    """SQLAlchemy 设置 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    def get(self, key: str) -> Optional[str]:
        row = self._session.get(AppSettingsModel, key)
        return row.value if row is not None else None

    def set(self, key: str, value: str) -> None:
        try:
            row = self._session.get(AppSettingsModel, key)
            if row is None:
                self._session.add(AppSettingsModel(key=key, value=value))
            else:
                row.value = value
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
