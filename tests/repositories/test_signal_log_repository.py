import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.db.repositories.signal_log import SQLAlchemySignalLogRepository, InMemorySignalLogRepository
from backend.db.models.signal_log import SignalLogModel


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestSQLAlchemySignalLogRepository:
    def test_add_and_update_processed_order(self, db_session):
        repo = SQLAlchemySignalLogRepository(db_session)
        log = repo.add(SignalLogModel(
            strategy_id="abc",
            endpoint="/api/jukuan_order",
            source_platform="joinquant",
            payload={"security": "000001.XSHE", "amount": 100},
        ))
        assert log.id is not None

        repo.update_processed_order(log.id, "order-123")
        found = repo.get(log.id)
        assert found.processed_order_id == "order-123"

    def test_update_error(self, db_session):
        repo = SQLAlchemySignalLogRepository(db_session)
        log = repo.add(SignalLogModel(
            endpoint="/api/jukuan_order",
            payload={"security": "000001.XSHE"},
        ))
        repo.update_error(log.id, "无效的 security")
        found = repo.get(log.id)
        assert found.error_msg == "无效的 security"


class TestInMemorySignalLogRepository:
    def test_update_error(self):
        repo = InMemorySignalLogRepository()
        log = SignalLogModel(endpoint="/api/jukuan_order", payload={})
        added = repo.add(log)
        repo.update_error(added.id, "失败")
        found = repo.get(added.id)
        assert found.error_msg == "失败"
