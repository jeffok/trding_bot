# config/settings.py
import os
import pytz
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 基础配置
    PROJECT_NAME: str = "Alpha-Sniper-V8"
    ENV: str = "production"  # development / production

    # 时区规范 (V8.3 强制)
    TZ_HK: str = "Asia/Hong_Kong"
    TZ_UTC: str = "UTC"

    # 数据库 (MariaDB)
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", 3306))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")
    DB_NAME: str = os.getenv("DB_NAME", "alpha_sniper_v8")

    # Redis
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))

    # Telegram
    TG_BOT_TOKEN: str = os.getenv("TG_BOT_TOKEN", "")
    TG_CHAT_ID: str = os.getenv("TG_CHAT_ID", "")

    # 交易所 (Binance/Bybit)
    EXCHANGE_ID: str = "binance"
    API_KEY: str = os.getenv("API_KEY", "")
    API_SECRET: str = os.getenv("API_SECRET", "")

    class Config:
        env_file = ".env"


settings = Settings()
HK_TZ = pytz.timezone(settings.TZ_HK)
UTC_TZ = pytz.timezone(settings.TZ_UTC)