import json
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    SERVER_HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))
    ROOT_PATH: str = os.getenv("ROOT_PATH", "").rstrip("/")
    BASE_URL: str = os.getenv("BASE_URL", "").rstrip("/")
    MINI_QMT_PATH: str = os.getenv("MINI_QMT_PATH", "")
    ACCOUNT_ID: str = os.getenv("ACCOUNT_ID", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    SOURCE_PLATFORM_WEBHOOKS: dict = json.loads(
        os.getenv("SOURCE_PLATFORM_WEBHOOKS", "{}")
    )
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
    PERSISTENCE_MODE: str = os.getenv("PERSISTENCE_MODE", "sqlite")
    # 挂起买单（调仓资金不足时延迟买入）等待卖单回款的最长分钟数
    PENDING_BUY_EXPIRE_MINUTES: int = int(os.getenv("PENDING_BUY_EXPIRE_MINUTES", "30"))
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./data/qmt_live_assistant.db"
    )
    CORS_ALLOW_ORIGINS: str = os.getenv("CORS_ALLOW_ORIGINS", "*")
    CORS_ALLOW_CREDENTIALS: str = os.getenv("CORS_ALLOW_CREDENTIALS", "false")


settings = Settings()
