import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.repositories.settings import (
    InMemorySettingsRepository,
    SQLAlchemySettingsRepository,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestInMemorySettingsRepository:
    def test_get_missing_returns_none(self):
        repo = InMemorySettingsRepository()
        assert repo.get("bark") is None

    def test_set_get_roundtrip(self):
        repo = InMemorySettingsRepository()
        repo.set("bark", '{"enabled": true}')
        assert repo.get("bark") == '{"enabled": true}'

    def test_set_overwrites_existing_key(self):
        repo = InMemorySettingsRepository()
        repo.set("bark", "v1")
        repo.set("bark", "v2")
        assert repo.get("bark") == "v2"


class TestSQLAlchemySettingsRepository:
    def test_get_missing_returns_none(self, db_session):
        repo = SQLAlchemySettingsRepository(db_session)
        assert repo.get("bark") is None

    def test_set_get_roundtrip(self, db_session):
        repo = SQLAlchemySettingsRepository(db_session)
        repo.set("bark", '{"enabled": true}')
        assert repo.get("bark") == '{"enabled": true}'

    def test_set_overwrites_existing_key(self, db_session):
        repo = SQLAlchemySettingsRepository(db_session)
        repo.set("bark", "v1")
        repo.set("bark", "v2")
        assert repo.get("bark") == "v2"

    def test_multiple_keys_independent(self, db_session):
        repo = SQLAlchemySettingsRepository(db_session)
        repo.set("bark", "b1")
        repo.set("other", "o1")
        assert repo.get("bark") == "b1"
        assert repo.get("other") == "o1"
