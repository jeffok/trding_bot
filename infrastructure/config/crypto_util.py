"""
加密解密工具模块
用于安全地加密/解密敏感配置数据（API密钥等）
使用AES-GCM算法，提供数据完整性和认证
"""

import base64
import logging
import os
import secrets
from typing import Optional, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

logger = logging.getLogger(__name__)


class CryptoError(Exception):
    """加密解密相关异常"""
    pass


class CryptoUtil:
    """
    加密工具类
    使用AES-GCM算法，支持密钥派生和随机盐生成
    """

    # 算法参数
    AES_KEY_SIZE = 32  # AES-256
    SALT_SIZE = 16  # 盐值长度
    NONCE_SIZE = 12  # GCM nonce长度（推荐12字节）
    PBKDF2_ITERATIONS = 100000  # PBKDF2迭代次数

    def __init__(self, master_key: Optional[str] = None):
        """
        初始化加密工具

        Args:
            master_key: 主密钥，如果为None则从环境变量读取
        """
        self.master_key = master_key or os.getenv('CRYPTO_MASTER_KEY')

        if not self.master_key:
            raise CryptoError("未提供主密钥，请设置CRYPTO_MASTER_KEY环境变量或传入master_key参数")

        if len(self.master_key) < 32:
            logger.warning("主密钥长度建议至少32个字符，当前长度可能不够安全")

        logger.info("加密工具初始化完成")

    def derive_key(self, salt: bytes) -> bytes:
        """
        从主密钥派生加密密钥

        Args:
            salt: 盐值

        Returns:
            bytes: 派生出的加密密钥
        """
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=self.AES_KEY_SIZE,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )

        # 将主密钥编码为字节
        master_key_bytes = self.master_key.encode('utf-8')

        return kdf.derive(master_key_bytes)

    def encrypt(self, plaintext: Union[str, bytes]) -> str:
        """
        加密数据

        Args:
            plaintext: 明文数据，可以是字符串或字节

        Returns:
            str: Base64编码的加密数据，格式为: salt.nonce.ciphertext.tag

        Raises:
            CryptoError: 加密失败时抛出
        """
        try:
            # 转换为字节
            if isinstance(plaintext, str):
                plaintext_bytes = plaintext.encode('utf-8')
            else:
                plaintext_bytes = plaintext

            # 生成随机盐和nonce
            salt = secrets.token_bytes(self.SALT_SIZE)
            nonce = secrets.token_bytes(self.NONCE_SIZE)

            # 派生密钥
            key = self.derive_key(salt)

            # 创建AES-GCM实例并加密
            aesgcm = AESGCM(key)
            ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)

            # 组合所有部分: salt + nonce + ciphertext
            # ciphertext已经包含了认证标签
            combined = salt + nonce + ciphertext

            # Base64编码
            encrypted_b64 = base64.urlsafe_b64encode(combined).decode('ascii')

            logger.debug(f"数据加密成功，原始长度: {len(plaintext_bytes)}，加密后长度: {len(encrypted_b64)}")
            return encrypted_b64

        except Exception as e:
            logger.error(f"数据加密失败: {e}")
            raise CryptoError(f"加密失败: {e}")

    def decrypt(self, encrypted_data: str) -> str:
        """
        解密数据

        Args:
            encrypted_data: Base64编码的加密数据，格式为: salt.nonce.ciphertext.tag

        Returns:
            str: 解密后的字符串

        Raises:
            CryptoError: 解密失败时抛出（数据被篡改或密钥错误）
        """
        try:
            # Base64解码
            combined = base64.urlsafe_b64decode(encrypted_data.encode('ascii'))

            # 拆分各部分
            salt = combined[:self.SALT_SIZE]
            nonce = combined[self.SALT_SIZE:self.SALT_SIZE + self.NONCE_SIZE]
            ciphertext = combined[self.SALT_SIZE + self.NONCE_SIZE:]

            # 派生密钥
            key = self.derive_key(salt)

            # 解密
            aesgcm = AESGCM(key)
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)

            # 解码为字符串
            plaintext = plaintext_bytes.decode('utf-8')

            logger.debug(f"数据解密成功，解密后长度: {len(plaintext)}")
            return plaintext

        except InvalidTag as e:
            logger.error(f"数据完整性验证失败，可能被篡改或密钥错误: {e}")
            raise CryptoError("解密失败：数据完整性验证失败")
        except Exception as e:
            logger.error(f"数据解密失败: {e}")
            raise CryptoError(f"解密失败: {e}")

    def encrypt_dict_value(self, data: dict, key: str) -> dict:
        """
        加密字典中的指定键值

        Args:
            data: 原始字典
            key: 需要加密的键名

        Returns:
            dict: 加密后的字典
        """
        if key not in data:
            logger.warning(f"字典中不存在键: {key}")
            return data

        try:
            data[key] = self.encrypt(data[key])
            logger.debug(f"字典键 '{key}' 加密完成")
            return data
        except Exception as e:
            logger.error(f"加密字典键 '{key}' 失败: {e}")
            raise

    def decrypt_dict_value(self, data: dict, key: str) -> dict:
        """
        解密字典中的指定键值

        Args:
            data: 加密后的字典
            key: 需要解密的键名

        Returns:
            dict: 解密后的字典
        """
        if key not in data:
            logger.warning(f"字典中不存在键: {key}")
            return data

        try:
            data[key] = self.decrypt(data[key])
            logger.debug(f"字典键 '{key}' 解密完成")
            return data
        except Exception as e:
            logger.error(f"解密字典键 '{key}' 失败: {e}")
            raise

    def verify_integrity(self, encrypted_data: str) -> bool:
        """
        验证加密数据的完整性（不进行解密）

        Args:
            encrypted_data: 加密数据

        Returns:
            bool: 数据是否完整有效
        """
        try:
            # 尝试解密但不返回结果
            self.decrypt(encrypted_data)
            return True
        except CryptoError:
            return False

    @staticmethod
    def generate_master_key(length: int = 32) -> str:
        """
        生成随机主密钥

        Args:
            length: 密钥长度，默认32

        Returns:
            str: 生成的随机密钥
        """
        if length < 16:
            raise ValueError("密钥长度至少16个字符")

        # 生成安全的随机密钥
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_-+=[]{}|;:,.<>?"
        key = ''.join(secrets.choice(alphabet) for _ in range(length))

        logger.info(f"生成 {length} 位主密钥")
        return key

    @staticmethod
    def generate_env_file(key: str, env_path: str = ".env") -> None:
        """
        生成.env文件模板，包含主密钥

        Args:
            key: 主密钥
            env_path: .env文件路径
        """
        template = f"""# 加密主密钥 - 务必保管好，丢失将无法解密数据
CRYPTO_MASTER_KEY={key}

# 数据库配置
DATABASE_URL=mysql+pymysql://user:password@localhost/quant_bot

# 日志级别
LOG_LEVEL=INFO

# 交易所API配置（将在Web界面配置并加密存储）
# BINANCE_API_KEY=
# BINANCE_API_SECRET=
# BYBIT_API_KEY=
# BYBIT_API_SECRET=

# AI服务配置
# OPENAI_API_KEY=
# DEEPSEEK_API_KEY=

# Telegram配置
# TELEGRAM_BOT_TOKEN=
"""

        try:
            with open(env_path, 'w') as f:
                f.write(template)
            logger.info(f".env文件已生成到: {env_path}")
            print(f"\n⚠️  重要提示：")
            print(f"1. 已生成主密钥: {key}")
            print(f"2. 请妥善保管 CRYPTO_MASTER_KEY，丢失将导致所有加密数据无法解密！")
            print(f"3. 请修改.env中的数据库连接信息")
            print(f"4. 不要将.env文件提交到版本控制系统！")
        except Exception as e:
            logger.error(f"生成.env文件失败: {e}")
            raise


# 全局加密工具实例
_crypto_instance: Optional[CryptoUtil] = None


def get_crypto() -> CryptoUtil:
    """
    获取全局加密工具实例（单例模式）

    Returns:
        CryptoUtil: 加密工具实例
    """
    global _crypto_instance

    if _crypto_instance is None:
        _crypto_instance = CryptoUtil()

    return _crypto_instance


def encrypt_value(value: str) -> str:
    """
    加密字符串（便捷函数）

    Args:
        value: 需要加密的字符串

    Returns:
        str: 加密后的字符串
    """
    return get_crypto().encrypt(value)


def decrypt_value(encrypted_value: str) -> str:
    """
    解密字符串（便捷函数）

    Args:
        encrypted_value: 加密的字符串

    Returns:
        str: 解密后的字符串
    """
    return get_crypto().decrypt(encrypted_value)


__all__ = [
    'CryptoError',
    'CryptoUtil',
    'get_crypto',
    'encrypt_value',
    'decrypt_value',
]