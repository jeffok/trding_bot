# database/db_manager.py
import pymysql
from sqlalchemy import create_engine, text
from config.settings import settings
from config.logging_config import setup_logger

logger = setup_logger("db_manager")


class DBManager:
    def __init__(self):
        # 构建连接字符串
        self.db_url = f"mysql+pymysql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
        self.engine = create_engine(
            self.db_url,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600
        )

    def init_db(self):
        """执行 schema.sql 初始化数据库"""
        try:
            # 读取 SQL 文件
            with open("database/schema.sql", "r", encoding="utf-8") as f:
                sql_script = f.read()

            # 分割语句 (简单分割，复杂场景可能需要更强的 parser)
            statements = [s.strip() for s in sql_script.split(';') if s.strip()]

            with self.engine.connect() as conn:
                for statement in statements:
                    conn.execute(text(statement))
                conn.commit()

            logger.info("Database schema initialized successfully.",
                        extra={"action": "INIT_DB", "reason_code": "STARTUP", "reason": "Schema applied"})
        except Exception as e:
            logger.error(f"Database initialization failed: {str(e)}",
                         extra={"action": "INIT_DB", "reason_code": "DB_ERROR", "reason": str(e)})
            raise

    def get_engine(self):
        return self.engine


# 简单的单例模式
db = DBManager()