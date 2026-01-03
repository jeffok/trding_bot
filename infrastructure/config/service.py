"""
配置中心服务
统一管理所有系统配置，支持加密存储、热重载和配置缓存
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from functools import lru_cache

from sqlalchemy.orm import Session

from ..database.models import SecureConfig
from .crypto_util import get_crypto, CryptoError

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """配置相关异常"""
    pass


class ConfigService:
    """
    配置中心服务
    提供配置的读写、加密、缓存和热重载功能
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        初始化配置服务

        Args:
            db_session: 数据库会话，如果为None则每次操作创建新会话
        """
        self.db_session = db_session
        self._crypto = get_crypto()
        self._config_cache: Dict[str, Any] = {}
        self._cache_timestamp = 0

        logger.info("配置服务初始化完成")

    def set_db_session(self, db_session: Session) -> None:
        """设置数据库会话"""
        self.db_session = db_session

    def _get_session(self) -> Session:
        """获取数据库会话"""
        if self.db_session is not None:
            return self.db_session

        # 如果没有提供会话，需要从外部获取
        # 这里只是返回None，实际使用时应该通过依赖注入获取
        raise ConfigError("数据库会话未设置")

    def get_config(
            self,
            group: str,
            key: str,
            default: Any = None,
            decrypt: bool = True
    ) -> Any:
        """
        获取配置值

        Args:
            group: 配置分组
            key: 配置键名
            default: 默认值（如果配置不存在）
            decrypt: 是否自动解密（如果配置已加密）

        Returns:
            Any: 配置值
        """
        cache_key = f"{group}.{key}"

        # 检查缓存
        if cache_key in self._config_cache:
            cached_value = self._config_cache[cache_key]
            if decrypt and isinstance(cached_value, str):
                try:
                    return self._crypto.decrypt(cached_value)
                except CryptoError:
                    # 如果解密失败，可能是未加密的值
                    return cached_value
            return cached_value

        session = self._get_session()

        try:
            config = session.query(SecureConfig).filter_by(
                group=group,
                key=key
            ).first()

            if config is None:
                logger.debug(f"配置不存在: {group}.{key}，返回默认值")
                return default

            value = config.value

            # 更新缓存
            self._config_cache[cache_key] = value

            # 如果需要解密且配置标记为已加密
            if decrypt and config.is_encrypted:
                try:
                    decrypted_value = self._crypto.decrypt(value)

                    # 尝试解析JSON
                    try:
                        return json.loads(decrypted_value)
                    except json.JSONDecodeError:
                        return decrypted_value

                except CryptoError as e:
                    logger.error(f"配置解密失败 {group}.{key}: {e}")
                    raise ConfigError(f"配置解密失败: {group}.{key}")

            # 未加密的值，尝试解析JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value

        except Exception as e:
            logger.error(f"获取配置失败 {group}.{key}: {e}")
            return default

    def get_group_configs(self, group: str, decrypt: bool = True) -> Dict[str, Any]:
        """
        获取指定分组的所有配置

        Args:
            group: 配置分组
            decrypt: 是否自动解密

        Returns:
            Dict[str, Any]: 分组配置字典
        """
        session = self._get_session()

        try:
            configs = session.query(SecureConfig).filter_by(group=group).all()

            result = {}
            for config in configs:
                cache_key = f"{group}.{config.key}"
                value = config.value

                # 更新缓存
                self._config_cache[cache_key] = value

                # 解密处理
                if decrypt and config.is_encrypted:
                    try:
                        decrypted_value = self._crypto.decrypt(value)
                        try:
                            result[config.key] = json.loads(decrypted_value)
                        except json.JSONDecodeError:
                            result[config.key] = decrypted_value
                    except CryptoError as e:
                        logger.error(f"配置解密失败 {group}.{config.key}: {e}")
                        result[config.key] = None
                else:
                    try:
                        result[config.key] = json.loads(value)
                    except json.JSONDecodeError:
                        result[config.key] = value

            logger.debug(f"获取分组配置: {group}，共 {len(result)} 项")
            return result

        except Exception as e:
            logger.error(f"获取分组配置失败 {group}: {e}")
            return {}

    def set_config(
            self,
            group: str,
            key: str,
            value: Any,
            encrypt: bool = True,
            description: Optional[str] = None,
            force_update: bool = False
    ) -> bool:
        """
        设置配置值

        Args:
            group: 配置分组
            key: 配置键名
            value: 配置值
            encrypt: 是否加密存储
            description: 配置描述
            force_update: 是否强制更新（即使值相同）

        Returns:
            bool: 是否成功
        """
        session = self._get_session()

        try:
            # 查询现有配置
            config = session.query(SecureConfig).filter_by(group=group, key=key).first()

            # 准备存储的值
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)

            # 加密处理
            if encrypt:
                encrypted_value = self._crypto.encrypt(value_str)
                is_encrypted = True
                store_value = encrypted_value
            else:
                is_encrypted = False
                store_value = value_str

            # 检查值是否变化
            if config and config.value == store_value and not force_update:
                logger.debug(f"配置未变化，跳过更新: {group}.{key}")
                return True

            if config:
                # 更新现有配置
                config.value = store_value
                config.is_encrypted = is_encrypted
                if description is not None:
                    config.description = description
                config.version += 1
                logger.info(f"更新配置: {group}.{key} (版本: {config.version})")
            else:
                # 创建新配置
                config = SecureConfig(
                    group=group,
                    key=key,
                    value=store_value,
                    is_encrypted=is_encrypted,
                    description=description or f"{group} {key} 配置"
                )
                session.add(config)
                logger.info(f"创建新配置: {group}.{key}")

            session.commit()

            # 更新缓存
            cache_key = f"{group}.{key}"
            self._config_cache[cache_key] = store_value

            return True

        except Exception as e:
            session.rollback()
            logger.error(f"设置配置失败 {group}.{key}: {e}")
            return False

    def delete_config(self, group: str, key: str) -> bool:
        """
        删除配置

        Args:
            group: 配置分组
            key: 配置键名

        Returns:
            bool: 是否成功
        """
        session = self._get_session()

        try:
            config = session.query(SecureConfig).filter_by(group=group, key=key).first()

            if config:
                session.delete(config)
                session.commit()

                # 清除缓存
                cache_key = f"{group}.{key}"
                if cache_key in self._config_cache:
                    del self._config_cache[cache_key]

                logger.info(f"删除配置: {group}.{key}")
                return True
            else:
                logger.warning(f"配置不存在，无法删除: {group}.{key}")
                return False

        except Exception as e:
            session.rollback()
            logger.error(f"删除配置失败 {group}.{key}: {e}")
            return False

    def import_configs(self, configs: List[Dict[str, Any]]) -> int:
        """
        批量导入配置

        Args:
            configs: 配置列表，每个元素包含 group, key, value, encrypt, description

        Returns:
            int: 成功导入的数量
        """
        success_count = 0

        for config_data in configs:
            try:
                group = config_data['group']
                key = config_data['key']
                value = config_data['value']
                encrypt = config_data.get('encrypt', True)
                description = config_data.get('description')

                if self.set_config(group, key, value, encrypt, description):
                    success_count += 1

            except Exception as e:
                logger.error(f"导入配置失败 {config_data}: {e}")

        logger.info(f"批量导入配置完成: 成功 {success_count}/{len(configs)}")
        return success_count

    def export_configs(self, group: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        导出配置

        Args:
            group: 指定分组，如果为None则导出所有

        Returns:
            List[Dict[str, Any]]: 配置列表
        """
        session = self._get_session()

        try:
            query = session.query(SecureConfig)
            if group:
                query = query.filter_by(group=group)

            configs = query.all()

            result = []
            for config in configs:
                config_dict = {
                    'group': config.group,
                    'key': config.key,
                    'value': config.value,  # 保持加密状态
                    'encrypt': config.is_encrypted,
                    'description': config.description,
                    'version': config.version,
                    'created_at': config.created_at.isoformat() if config.created_at else None,
                    'updated_at': config.updated_at.isoformat() if config.updated_at else None,
                }
                result.append(config_dict)

            return result

        except Exception as e:
            logger.error(f"导出配置失败: {e}")
            return []

    def clear_cache(self) -> None:
        """清除配置缓存"""
        self._config_cache.clear()
        logger.info("配置缓存已清除")

    def reload_cache(self) -> None:
        """重新加载所有配置到缓存"""
        session = self._get_session()

        try:
            all_configs = session.query(SecureConfig).all()

            self._config_cache.clear()
            for config in all_configs:
                cache_key = f"{config.group}.{config.key}"
                self._config_cache[cache_key] = config.value

            logger.info(f"配置缓存已重新加载，共 {len(all_configs)} 项")

        except Exception as e:
            logger.error(f"重新加载缓存失败: {e}")

    def health_check(self) -> Dict[str, Any]:
        """
        配置服务健康检查

        Returns:
            Dict[str, Any]: 健康状态信息
        """
        session = self._get_session()

        try:
            # 统计配置数量
            total_count = session.query(SecureConfig).count()

            # 按分组统计
            group_stats = {}
            groups = session.query(SecureConfig.group).distinct().all()
            for group_tuple in groups:
                group = group_tuple[0]
                count = session.query(SecureConfig).filter_by(group=group).count()
                group_stats[group] = count

            # 加密配置统计
            encrypted_count = session.query(SecureConfig).filter_by(is_encrypted=True).count()

            return {
                'status': 'healthy',
                'total_configs': total_count,
                'encrypted_configs': encrypted_count,
                'cache_size': len(self._config_cache),
                'groups': group_stats,
            }

        except Exception as e:
            logger.error(f"配置服务健康检查失败: {e}")
            return {
                'status': 'unhealthy',
                'error': str(e),
            }

    @lru_cache(maxsize=128)
    def get_cached_config(self, group: str, key: str, default: Any = None) -> Any:
        """
        获取配置（带LRU缓存）

        Args:
            group: 配置分组
            key: 配置键名
            default: 默认值

        Returns:
            Any: 配置值
        """
        return self.get_config(group, key, default)


# 全局配置服务实例
_config_service: Optional[ConfigService] = None


def get_config_service(db_session: Optional[Session] = None) -> ConfigService:
    """
    获取全局配置服务实例

    Args:
        db_session: 数据库会话

    Returns:
        ConfigService: 配置服务实例
    """
    global _config_service

    if _config_service is None:
        _config_service = ConfigService(db_session)
    elif db_session is not None:
        _config_service.set_db_session(db_session)

    return _config_service


# 常用配置获取函数
def get_exchange_config(exchange: str, key: str, default: Any = None) -> Any:
    """
    获取交易所配置（便捷函数）

    Args:
        exchange: 交易所名称，如: binance, bybit
        key: 配置键名，如: api_key, api_secret
        default: 默认值

    Returns:
        Any: 配置值
    """
    service = get_config_service()
    return service.get_config(f"exchange_{exchange}", key, default)


def get_ai_config(provider: str, key: str, default: Any = None) -> Any:
    """
    获取AI服务配置（便捷函数）

    Args:
        provider: AI服务提供商，如: openai, deepseek
        key: 配置键名，如: api_key, model
        default: 默认值

    Returns:
        Any: 配置值
    """
    service = get_config_service()
    return service.get_config(f"ai_{provider}", key, default)


def get_telegram_config(key: str, default: Any = None) -> Any:
    """
    获取Telegram配置（便捷函数）

    Args:
        key: 配置键名，如: bot_token, chat_id
        default: 默认值

    Returns:
        Any: 配置值
    """
    service = get_config_service()
    return service.get_config("telegram", key, default)


__all__ = [
    'ConfigError',
    'ConfigService',
    'get_config_service',
    'get_exchange_config',
    'get_ai_config',
    'get_telegram_config',
]