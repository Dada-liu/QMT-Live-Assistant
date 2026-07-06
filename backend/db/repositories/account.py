"""账户 Repository。"""
from typing import List, Optional
from sqlalchemy.orm import Session
from backend.db.models.account import AccountModel
from backend.db.repositories.base import Repository, InMemoryRepository


class AccountRepository(Repository[AccountModel]):
    """账户 Repository 接口。"""

    def get_by_account_id(self, account_id: str) -> Optional[AccountModel]: ...


class InMemoryAccountRepository(InMemoryRepository[AccountModel], AccountRepository):
    """内存账户 Repository。"""

    def get_by_account_id(self, account_id: str) -> Optional[AccountModel]:
        for account in self._store.values():
            if account.account_id == account_id:
                return account
        return None


class SQLAlchemyAccountRepository(AccountRepository):
    """SQLAlchemy 账户 Repository。"""

    def __init__(self, session: Session):
        self._session = session

    def add(self, entity: AccountModel) -> AccountModel:
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get(self, id: str) -> Optional[AccountModel]:
        return self._session.get(AccountModel, id)

    def get_by_account_id(self, account_id: str) -> Optional[AccountModel]:
        return (
            self._session.query(AccountModel)
            .filter_by(account_id=account_id)
            .first()
        )

    def update(self, entity: AccountModel) -> AccountModel:
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

    def list_all(self, **filters) -> List[AccountModel]:
        query = self._session.query(AccountModel)
        for key, value in filters.items():
            if hasattr(AccountModel, key) and value is not None:
                query = query.filter(getattr(AccountModel, key) == value)
        return query.all()
