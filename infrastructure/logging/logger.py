"""
结构化日志系统
提供统一的日志配置和管理，支持数据库日志、文件日志和控制台日志
"""

import logging
import logging.handlers
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from ...database.models import SystemLog, LogLevel
from ..database.session import db_manager


class StructuredFormatter(logging.Formatter):
    """结构化日志格式化器"""

    def __init__(self, fmt=None, datefmt=None, style='%'):
        super().__init__(fmt, datefmt, style)

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为结构化JSON"""
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'message': record.getMessage(),
            'process': record.process,
            'thread': record.threadName,
        }

        # 添加额外字段
        if hasattr(record, 'extra') and record.extra:
            log_data['extra'] = record.extra

        # 添加异常信息
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # 添加堆栈信息（如果是错误级别）
        if record.levelno >= logging.ERROR and record.stack_info:
            log_data['stack'] = record.stack_info

        return json.dumps(log_data, ensure_ascii=False)


class DatabaseLogHandler(logging.Handler):
    """数据库日志处理器"""

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record: logging.LogRecord) -> None:
        """将日志记录写入数据库"""
        try:
            # 映射日志级别
            level_mapping = {
                logging.DEBUG: LogLevel.DEBUG,
                logging.INFO: LogLevel.INFO,
                logging.WARNING: LogLevel.WARNING,
                logging.ERROR: LogLevel.ERROR,
                logging.CRITICAL: LogLevel.CRITICAL,
            }

            log_level = level_mapping.get(record.levelno, LogLevel.INFO)

            # 准备额外数据
            extra_data = {}
            if hasattr(record, 'extra') and record.extra:
                extra_data = record.extra

            # 获取异常信息
            exc_info = None
            if record.exc_info:
                exc_info = self.formatException(record.exc_info)

            # 创建日志记录
            log_entry = SystemLog(
                level=log_level,
                logger_name=record.name,
                module=record.module,
                function=record.funcName,
                line_no=record.lineno,
                message=record.getMessage(),
                exc_info=exc_info,
                extra=extra_data,
            )

            # 写入数据库
            with db_manager.get_session() as session:
                session.add(log_entry)
                session.commit()

        except Exception as e:
            # 避免递归错误
            print(f"数据库日志记录失败: {e}", file=sys.stderr)


class LoggerFactory:
    """日志记录器工厂"""

    _loggers: Dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(
            cls,
            name: str = 'quant_bot',
            level: str = 'INFO',
            enable_file: bool = True,
            enable_console: bool = True,
            enable_database: bool = True,
            log_dir: Optional[str] = None
    ) -> logging.Logger:
        """
        获取或创建日志记录器

        Args:
            name: 记录器名称
            level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
            enable_file: 是否启用文件日志
            enable_console: 是否启用控制台日志
            enable_database: 是否启用数据库日志
            log_dir: 日志目录，如果为None则使用当前目录的logs子目录

        Returns:
            logging.Logger: 配置好的日志记录器
        """
        # 如果记录器已存在，直接返回
        if name in cls._loggers:
            return cls._loggers[name]

        # 创建新记录器
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper()))

        # 清除现有处理器（避免重复）
        logger.handlers.clear()

        # 创建格式化器
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        json_formatter = StructuredFormatter()

        # 控制台处理器
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, level.upper()))
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)

        # 文件处理器
        if enable_file:
            # 创建日志目录
            if log_dir is None:
                log_dir = Path.cwd() / 'logs'
            else:
                log_dir = Path(log_dir)

            log_dir.mkdir(exist_ok=True)

            # 按日期滚动的文件处理器
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_dir / 'quant_bot.log',
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            file_handler.setLevel(getattr(logging, level.upper()))
            file_handler.setFormatter(json_formatter)
            logger.addHandler(file_handler)

            # 错误日志单独文件
            error_handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_dir / 'quant_bot_error.log',
                when='midnight',
                interval=1,
                backupCount=30,
                encoding='utf-8'
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(json_formatter)
            logger.addHandler(error_handler)

        # 数据库处理器
        if enable_database:
            try:
                db_handler = DatabaseLogHandler()
                db_handler.setLevel(logging.INFO)  # 数据库只记录INFO及以上级别
                logger.addHandler(db_handler)
            except Exception as e:
                print(f"数据库日志处理器初始化失败: {e}", file=sys.stderr)

        # 避免日志传播到根记录器
        logger.propagate = False

        # 缓存记录器
        cls._loggers[name] = logger

        return logger

    @classmethod
    def configure_root_logger(cls, **kwargs) -> None:
        """配置根日志记录器"""
        cls.get_logger('', **kwargs)

    @classmethod
    def get_module_logger(cls, module_name: str) -> logging.Logger:
        """获取模块日志记录器"""
        return cls.get_logger(f'quant_bot.{module_name}')


def setup_logging(
        config: Optional[Dict[str, Any]] = None,
        default_level: str = 'INFO'
) -> None:
    """
    设置全局日志配置

    Args:
        config: 日志配置字典
        default_level: 默认日志级别
    """
    if config is None:
        config = {}

    level = config.get('level', default_level)
    enable_file = config.get('enable_file', True)
    enable_console = config.get('enable_console', True)
    enable_database = config.get('enable_database', True)
    log_dir = config.get('log_dir')

    # 配置根日志记录器
    LoggerFactory.configure_root_logger(
        level=level,
        enable_file=enable_file,
        enable_console=enable_console,
        enable_database=enable_database,
        log_dir=log_dir
    )

    # 设置第三方库日志级别
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('ccxt').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器（便捷函数）

    Args:
        name: 记录器名称

    Returns:
        logging.Logger: 日志记录器
    """
    return LoggerFactory.get_logger(name)


# 常用模块日志记录器
def get_trading_logger() -> logging.Logger:
    """获取交易模块日志记录器"""
    return get_logger('quant_bot.trading')


def get_strategy_logger() -> logging.Logger:
    """获取策略模块日志记录器"""
    return get_logger('quant_bot.strategy')


def get_web_logger() -> logging.Logger:
    """获取Web模块日志记录器"""
    return get_logger('quant_bot.web')


def get_db_logger() -> logging.Logger:
    """获取数据库模块日志记录器"""
    return get_logger('quant_bot.database')


def get_ai_logger() -> logging.Logger:
    """获取AI模块日志记录器"""
    return get_logger('quant_bot.ai')


__all__ = [
    'LoggerFactory',
    'setup_logging',
    'get_logger',
    'get_trading_logger',
    'get_strategy_logger',
    'get_web_logger',
    'get_db_logger',
    'get_ai_logger',
]