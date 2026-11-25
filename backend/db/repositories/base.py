"""Repository 抽象基类与通用内存实现。"""
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional, Dict

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    """通用 Repository 接口。"""

    @abstractmethod
    def add(self, entity: T) -> T: ...

    @abstractmethod
    def get(self, id: str) -> Optional[T]: ...

    @abstractmethod
    def update(self, entity: T) -> T: ...

    @abstractmethod
    def delete(self, id: str) -> bool: ...

    @abstractmethod
    def list_all(self, **filters) -> List[T]: ...


class InMemoryRepository(Repository[T], Generic[T]):
    """通用内存 Repository 实现，用于测试和 fallback。"""

    def __init__(self):
        self._store: Dict[str, T] = {}

    def add(self, entity: T) -> T:
        entity_id = getattr(entity, "id")
        self._store[entity_id] = entity
        return entity

    def get(self, id: str) -> Optional[T]:
        return self._store.get(id)

    def update(self, entity: T) -> T:
        entity_id = getattr(entity, "id")
        self._store[entity_id] = entity
        return entity

    def delete(self, id: str) -> bool:
        if id in self._store:
            del self._store[id]
            return True
        return False

    def list_all(self, **filters) -> List[T]:
        result = list(self._store.values())
        for key, value in filters.items():
            if value is not None:
                result = [e for e in result if getattr(e, key, None) == value]
        return result
