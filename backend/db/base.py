"""数据库基础设施。

提供 SQLAlchemy Base、引擎和会话工厂，以及 ID 生成工具函数。
"""
import functools
import threading
import uuid
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from config.settings import settings

Base = declarative_base()


def uuid4_str() -> str:
    """生成不带连字符的 UUID 字符串，用于数据库主键。"""
    return uuid.uuid4().hex


db_lock = threading.RLock()
"""全局数据库锁：串行化所有 SQLAlchemy Repository 对共享 Session 的访问。

SQLAlchemy Session 非线程安全，而本项目的全局单例 Session 会被
事件循环线程、run_blocking 工作线程与 xtquant 回调线程并发使用。
必须用 RLock（可重入）：部分 repo 方法内部会调用本 repo 的
其他加锁方法（如 update_processed_order 内部调用 get）。
sqlite 本地操作为微秒级，串行化对吞吐无实质影响。
"""


def synchronized(func):
    """用全局 db_lock 串行化 Repository 公开方法（整方法粒度）。

    不能用 session 代理代替：repo 典型用法 query().filter_by().all()
    中 .all() 才触库并写 session identity map，代理入口盖不住链尾。
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with db_lock:
            return func(*args, **kwargs)
    return wrapper


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={
        "check_same_thread": False,
        # sqlite busy timeout（秒）：写锁竞争时等待上限，避免默认 5s 过短
        # 导致高并发下频繁 database is locked。
        "timeout": 15,
    } if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        """启用 WAL：读不阻塞写、写不阻塞读，降低多线程（事件循环工作线程
        与 xtquant 回调线程）并发访问时的锁冲突。
        :memory: 测试库不支持 WAL，pragma 静默返回 memory 模式，不报错。"""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
