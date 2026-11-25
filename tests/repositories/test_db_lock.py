"""全局数据库锁（db_lock / @synchronized）测试。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import threading
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base, db_lock
from backend.db.repositories.order import SQLAlchemyOrderRepository
from backend.models.order import TrackedOrder


def test_db_lock_is_reentrant():
    """同线程可重复获取（repo 方法内嵌套调用加锁方法时不会死锁）。"""
    with db_lock:
        with db_lock:
            pass


def test_concurrent_read_write_serialized(tmp_path):
    """多线程并发读写同一共享 session：加锁后应无异常且数据完整。"""
    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    repo = SQLAlchemyOrderRepository(session)

    errors = []

    def writer(start):
        try:
            for i in range(start, start + 25):
                repo.save(TrackedOrder(
                    order_id=str(100000 + i),
                    stock_code="000001.SZ",
                    jq_code="000001.XSHE",
                    direction="buy",
                    quantity=100,
                    order_type=23,
                    strategy_id="abc",
                    strategy_name="并发测试",
                    price=10.0,
                ))
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(50):
                repo.list_all()
                repo.list_pending()
                repo.get_by_id("100000")
        except Exception as e:
            errors.append(e)

    threads = (
        [threading.Thread(target=writer, args=(n * 25,)) for n in range(2)]
        + [threading.Thread(target=reader) for _ in range(2)]
    )
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "有线程未结束（疑似死锁）"
    assert errors == []
    assert len(repo.list_all()) == 50
    session.close()
