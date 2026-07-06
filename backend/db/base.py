"""数据库基础设施。

提供 SQLAlchemy Base、引擎和会话工厂，以及 ID 生成工具函数。
"""
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config.settings import settings

Base = declarative_base()


def uuid4_str() -> str:
    """生成不带连字符的 UUID 字符串，用于数据库主键。"""
    return uuid.uuid4().hex


_engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={
        "check_same_thread": False,
    } if settings.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
