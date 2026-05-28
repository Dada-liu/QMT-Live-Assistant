import os


class Settings:
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))
    MINI_QMT_PATH: str = os.getenv("MINI_QMT_PATH", "")
    ACCOUNT_ID: str = os.getenv("ACCOUNT_ID", "")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default-secret-key-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    WECHAT_WEBHOOK_URL: str = os.getenv("WECHAT_WEBHOOK_URL", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "")
    DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")


settings = Settings()
