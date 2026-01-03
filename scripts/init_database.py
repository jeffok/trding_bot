#!/usr/bin/env python3
"""
数据库初始化脚本
创建所有数据表，并插入必要的初始数据
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import logging
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.database.session import db_manager
from app.infrastructure.database.models import (
    Base, AssetAccount, TradingPair, ExecutionPolicy, AccountType, OrderType
)
from app.infrastructure.config.crypto_util import CryptoUtil
from app.infrastructure.logging.logger import setup_logging


def init_logging():
    """初始化日志"""
    setup_logging({
        'level': 'INFO',
        'enable_console': True,
        'enable_file': False,
        'enable_database': False,
    })


def create_tables():
    """创建所有数据库表"""
    print("=" * 60)
    print("开始创建数据库表...")
    print("=" * 60)

    try:
        db_manager.create_tables()
        print("✅ 数据库表创建成功！")
        print(f"共创建了 {len(Base.metadata.tables)} 张表")

        # 显示创建的表
        print("\n创建的表清单:")
        for i, table_name in enumerate(sorted(Base.metadata.tables.keys()), 1):
            print(f"  {i:2d}. {table_name}")

    except Exception as e:
        print(f"❌ 创建数据库表失败: {e}")
        sys.exit(1)


def insert_initial_data():
    """插入初始数据"""
    print("\n" + "=" * 60)
    print("开始插入初始数据...")
    print("=" * 60)

    with db_manager.get_session() as session:
        try:
            # 1. 插入示例交易对配置
            print("\n1. 插入示例交易对配置...")
            trading_pairs = [
                TradingPair(
                    base_symbol="BTC/USDT",
                    exchange="binance",
                    account_type=AccountType.FUTURE,
                    exchange_symbol="BTCUSDT",
                    is_enabled=True,
                    config={"leverage": 10, "min_qty": 0.001}
                ),
                TradingPair(
                    base_symbol="ETH/USDT",
                    exchange="binance",
                    account_type=AccountType.FUTURE,
                    exchange_symbol="ETHUSDT",
                    is_enabled=True,
                    config={"leverage": 10, "min_qty": 0.01}
                ),
                TradingPair(
                    base_symbol="BTC/USDT",
                    exchange="bybit",
                    account_type=AccountType.FUTURE,
                    exchange_symbol="BTCUSDT",
                    is_enabled=True,
                    config={"leverage": 10, "min_qty": 0.001}
                ),
            ]

            session.add_all(trading_pairs)
            print(f"   ✅ 插入了 {len(trading_pairs)} 个交易对配置")

            # 2. 插入执行策略
            print("\n2. 插入执行策略...")

            # 获取刚插入的交易对ID
            btc_binance_future = session.query(TradingPair).filter_by(
                base_symbol="BTC/USDT",
                exchange="binance",
                account_type=AccountType.FUTURE
            ).first()

            btc_bybit_future = session.query(TradingPair).filter_by(
                base_symbol="BTC/USDT",
                exchange="bybit",
                account_type=AccountType.FUTURE
            ).first()

            execution_policies = [
                ExecutionPolicy(
                    name="single_binance",
                    multi_exchange_mode=False,
                    target_pairs=[btc_binance_future.id],
                    order_type=OrderType.MARKET,
                    description="单交易所执行策略（币安）"
                ),
                ExecutionPolicy(
                    name="multi_exchange",
                    multi_exchange_mode=True,
                    target_pairs=[btc_binance_future.id, btc_bybit_future.id],
                    order_type=OrderType.LIMIT,
                    limit_pullback_ratio=0.005,
                    entry_timeout_seconds=300,
                    max_chase_atr_ratio=0.3,
                    description="多交易所同时执行策略"
                ),
            ]

            session.add_all(execution_policies)
            print(f"   ✅ 插入了 {len(execution_policies)} 个执行策略")

            session.commit()
            print("\n✅ 初始数据插入完成！")

        except Exception as e:
            session.rollback()
            print(f"❌ 插入初始数据失败: {e}")
            sys.exit(1)


def generate_master_key():
    """生成主密钥"""
    print("\n" + "=" * 60)
    print("加密主密钥设置")
    print("=" * 60)

    try:
        key = CryptoUtil.generate_master_key(32)
        CryptoUtil.generate_env_file(key, project_root / ".env.example")

        print("\n🔐 重要安全提示:")
        print("   1. 主密钥已生成并保存到 .env.example 文件")
        print("   2. 请复制 .env.example 为 .env 并修改数据库连接信息")
        print("   3. 请妥善保管 CRYPTO_MASTER_KEY，丢失将无法解密数据！")
        print("   4. 生产环境请使用更安全的方式管理密钥（如密钥管理服务）")

    except Exception as e:
        print(f"❌ 生成主密钥失败: {e}")


def health_check():
    """数据库健康检查"""
    print("\n" + "=" * 60)
    print("数据库健康检查...")
    print("=" * 60)

    try:
        if db_manager.health_check():
            print("✅ 数据库连接正常")

            # 检查表数量
            with db_manager.get_session() as session:
                from sqlalchemy import text
                result = session.execute(
                    text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"))
                table_count = result.scalar()
                print(f"   数据库中存在 {table_count} 张表")

                # 检查各表记录数
                print("\n   各表记录数统计:")
                for table_name in sorted(Base.metadata.tables.keys()):
                    try:
                        result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                        count = result.scalar()
                        print(f"     {table_name:20s}: {count}")
                    except:
                        print(f"     {table_name:20s}: (表可能不存在)")

        else:
            print("❌ 数据库连接异常")

    except Exception as e:
        print(f"❌ 健康检查失败: {e}")


def main():
    """主函数"""
    print("🚀 交易系统数据库初始化工具")
    print("=" * 60)

    init_logging()

    # 检查数据库配置
    env_file = project_root / ".env"
    if not env_file.exists():
        print(f"⚠️  未找到 .env 文件，请先复制 .env.example 并配置数据库连接")
        print(f"   示例文件: {project_root / '.env.example'}")
        response = input("   是否生成示例.env文件？ (y/n): ")
        if response.lower() == 'y':
            generate_master_key()
        return

    # 从.env读取数据库配置（简化版）
    try:
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('DATABASE_URL='):
                    database_url = line.strip().split('=', 1)[1]
                    break
            else:
                print("❌ 在.env文件中未找到DATABASE_URL配置")
                return
    except Exception as e:
        print(f"❌ 读取.env文件失败: {e}")
        return

    # 初始化数据库
    try:
        db_manager.init_db(
            database_url=database_url,
            pool_size=5,
            max_overflow=2,
            echo=False
        )
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print(f"   请检查数据库URL: {database_url}")
        return

    # 显示菜单
    while True:
        print("\n" + "=" * 60)
        print("请选择操作:")
        print("  1. 创建所有表（首次安装）")
        print("  2. 插入初始数据")
        print("  3. 生成主密钥和.env示例")
        print("  4. 数据库健康检查")
        print("  5. 删除所有表（危险！仅开发测试）")
        print("  6. 执行完整初始化（1+2+3）")
        print("  0. 退出")
        print("=" * 60)

        choice = input("请输入选项 [0-6]: ").strip()

        if choice == '1':
            create_tables()
        elif choice == '2':
            insert_initial_data()
        elif choice == '3':
            generate_master_key()
        elif choice == '4':
            health_check()
        elif choice == '5':
            confirm = input("⚠️  确认删除所有表？此操作不可逆！(输入'YES'确认): ")
            if confirm == 'YES':
                db_manager.drop_tables()
                print("✅ 所有表已删除")
            else:
                print("操作已取消")
        elif choice == '6':
            create_tables()
            insert_initial_data()
            health_check()
        elif choice == '0':
            print("👋 退出初始化工具")
            break
        else:
            print("❌ 无效选项")


if __name__ == "__main__":
    main()