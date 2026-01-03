"""
数据库会话工厂与连接管理
提供线程安全的数据库会话，支持连接池配置
"""

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import QueuePool

from .models import Base

logger = logging.getLogger(__name__)


class DatabaseSessionManager:
    """
    数据库会话管理器
    单例模式，管理数据库连接池和会话工厂
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化数据库连接管理器"""
        if self._initialized:
            return

        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._scoped_session_factory = None
        self._initialized = True

        logger.debug("数据库会话管理器初始化完成")

    def init_db(
            self,
            database_url: str,
            pool_size: int = 20,
            max_overflow: int = 10,
            pool_timeout: int = 30,
            pool_recycle: int = 3600,
            echo: bool = False,
            **kwargs
    ) -> None:
        """
        初始化数据库连接

        Args:
            database_url: 数据库连接URL，如: mysql+pymysql://user:pass@localhost/dbname
            pool_size: 连接池大小，默认20
            max_overflow: 最大溢出连接数，默认10
            pool_timeout: 连接超时时间（秒），默认30
            pool_recycle: 连接回收时间（秒），默认3600
            echo: 是否输出SQL日志，默认False（生产环境建议False）
            **kwargs: 其他SQLAlchemy引擎参数
        """
        if self._engine is not None:
            logger.warning("数据库引擎已经初始化，跳过重复初始化")
            return

        # 创建数据库引擎
        engine_kwargs = {
            'poolclass': QueuePool,
            'pool_size': pool_size,
            'max_overflow': max_overflow,
            'pool_timeout': pool_timeout,
            'pool_recycle': pool_recycle,
            'echo': echo,
            'echo_pool': echo,
            'future': True,  # 使用SQLAlchemy 2.0风格
        }
        engine_kwargs.update(kwargs)

        try:
            self._engine = create_engine(database_url, **engine_kwargs)

            # 添加连接池事件监听
            self._setup_engine_events()

            # 创建会话工厂
            self._session_factory = sessionmaker(
                bind=self._engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
                class_=Session,
            )

            # 创建scoped session（线程安全）
            self._scoped_session_factory = scoped_session(self._session_factory)

            logger.info(f"数据库引擎初始化成功，URL: {database_url}")
            logger.info(f"连接池配置: size={pool_size}, overflow={max_overflow}, recycle={pool_recycle}s")

        except Exception as e:
            logger.error(f"数据库引擎初始化失败: {e}")
            raise

    def _setup_engine_events(self) -> None:
        """设置数据库引擎事件监听"""

        @event.listens_for(self._engine, "connect")
        def set_sql_mode(dbapi_connection, connection_record):
            """设置MySQL/MariaDB SQL模式"""
            cursor = dbapi_connection.cursor()
            cursor.execute(
                "SET SESSION sql_mode='STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
            cursor.close()
            logger.debug("SQL模式已设置")

        @event.listens_for(self._engine, "checkout")
        def on_checkout(dbapi_connection, connection_record, connection_proxy):
            """连接检出事件"""
            logger.debug("数据库连接检出")

        @event.listens_for(self._engine, "checkin")
        def on_checkin(dbapi_connection, connection_record):
            """连接归还事件"""
            logger.debug("数据库连接归还")

    def create_tables(self, check_first: bool = True) -> None:
        """
        创建所有数据库表

        Args:
            check_first: 是否检查表是否已存在，默认True
        """
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化，请先调用init_db()")

        try:
            logger.info("开始创建数据库表...")
            Base.metadata.create_all(self._engine, checkfirst=check_first)
            logger.info("数据库表创建完成")
        except Exception as e:
            logger.error(f"创建数据库表失败: {e}")
            raise

    def drop_tables(self, check_first: bool = True) -> None:
        """
        删除所有数据库表（谨慎使用！）

        Args:
            check_first: 是否检查表是否存在，默认True
        """
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化")

        try:
            logger.warning("开始删除所有数据库表...")
            Base.metadata.drop_all(self._engine, checkfirst=check_first)
            logger.warning("所有数据库表已删除")
        except Exception as e:
            logger.error(f"删除数据库表失败: {e}")
            raise

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        获取数据库会话上下文管理器

        使用示例:
            with db_manager.get_session() as session:
                # 使用session进行数据库操作
                result = session.query(User).filter_by(id=1).first()

        Yields:
            Session: SQLAlchemy会话对象

        Raises:
            RuntimeError: 数据库未初始化时抛出
        """
        if self._scoped_session_factory is None:
            raise RuntimeError("数据库未初始化，请先调用init_db()")

        session: Session = self._scoped_session_factory()

        try:
            yield session
            session.commit()
            logger.debug("数据库会话提交成功")
        except Exception as e:
            session.rollback()
            logger.error(f"数据库操作失败，已回滚: {e}")
            raise
        finally:
            session.close()
            # 移除scoped session的线程本地存储
            self._scoped_session_factory.remove()
            logger.debug("数据库会话已关闭")

    def get_raw_session(self) -> Session:
        """
        获取原始会话对象（需要手动管理生命周期）

        注意：使用此方法需要手动调用commit/rollback/close

        Returns:
            Session: SQLAlchemy会话对象
        """
        if self._session_factory is None:
            raise RuntimeError("数据库未初始化")

        session = self._session_factory()
        logger.debug("创建原始数据库会话")
        return session

    def get_engine(self) -> Engine:
        """
        获取数据库引擎

        Returns:
            Engine: SQLAlchemy引擎对象

        Raises:
            RuntimeError: 数据库未初始化时抛出
        """
        if self._engine is None:
            raise RuntimeError("数据库引擎未初始化")
        return self._engine

    def dispose_pool(self) -> None:
        """释放连接池中的所有连接"""
        if self._engine is not None:
            self._engine.dispose()
            logger.info("数据库连接池已释放")

    def health_check(self) -> bool:
        """
        数据库健康检查

        Returns:
            bool: 数据库连接是否正常
        """
        if self._engine is None:
            return False

        try:
            with self._engine.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"数据库健康检查失败: {e}")
            return False

    def get_pool_status(self) -> dict:
        """
        获取连接池状态信息

        Returns:
            dict: 连接池状态字典
        """
        if self._engine is None:
            return {"error": "数据库引擎未初始化"}

        pool = self._engine.pool
        return {
            "size": pool.size(),
            "checkedout": pool.checkedout(),
            "overflow": pool.overflow(),
            "checkedin": pool.checkedin(),
            "connections": pool.checkedin() + pool.checkedout(),
        }


# 创建全局数据库管理器实例
db_manager = DatabaseSessionManager()


# 便捷函数，用于快速获取会话
def get_db() -> Generator[Session, None, None]:
    """
    依赖注入函数，供FastAPI等框架使用

    使用示例（FastAPI）:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            items = db.query(Item).all()
            return items

    Yields:
        Session: 数据库会话
    """
    with db_manager.get_session() as session:
        yield session


__all__ = ['DatabaseSessionManager', 'db_manager', 'get_db']