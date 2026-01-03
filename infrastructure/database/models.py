"""
数据库ORM模型定义 - 对应"交易执行核心"系统的所有数据表
使用SQLAlchemy ORM，支持MariaDB/MySQL
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    Column, Integer, String, BigInteger, Boolean,
    DECIMAL, DateTime, Text, JSON, Enum, ForeignKey,
    Index, UniqueConstraint, CheckConstraint, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

# 声明基类
Base = declarative_base()


class AccountType(PyEnum):
    """账户类型枚举"""
    SPOT = "spot"  # 现货账户
    FUTURE = "future"  # 合约账户
    # 预留未来扩展：MARGIN = "margin", OPTION = "option"


class OrderSide(PyEnum):
    """订单方向枚举"""
    BUY = "buy"
    SELL = "sell"


class OrderType(PyEnum):
    """订单类型枚举"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


class OrderStatus(PyEnum):
    """订单状态枚举"""
    NEW = "new"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalAction(PyEnum):
    """信号动作枚举"""
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"
    ENTER_SHORT = "enter_short"
    EXIT_SHORT = "exit_short"
    HOLD = "hold"


class LogLevel(PyEnum):
    """日志级别枚举"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AssetAccount(Base):
    """
    资金账户表 - 管理不同交易所、不同类型的账户
    支持多交易所多账户并行管理
    """
    __tablename__ = "asset_account"

    # 主键与基础信息
    id = Column(String(50), primary_key=True, comment='账户唯一标识，如: binance_spot_main')
    name = Column(String(100), nullable=False, comment='账户显示名称')

    # 交易所与账户类型
    exchange = Column(String(20), nullable=False, comment='交易所标识，如: binance, bybit')
    account_type = Column(Enum(AccountType), nullable=False, comment='账户类型: spot/future')

    # 资金信息
    base_currency = Column(String(10), default='USDT', comment='基准货币')
    total_balance = Column(DECIMAL(30, 12), default=0, comment='总资产估值（基准货币）')
    available_balance = Column(DECIMAL(30, 12), default=0, comment='可用保证金')

    # 合约账户特有字段
    leverage = Column(Integer, default=1, comment='杠杆倍数（仅合约账户有效）')
    margin_mode = Column(String(20), default='isolated', comment='保证金模式: isolated/crossed')
    liquidation_price = Column(DECIMAL(30, 12), nullable=True, comment='强平价（仅合约）')

    # 状态与元数据
    is_virtual = Column(Boolean, default=False, comment='是否为虚拟分账户（用于策略资金隔离）')
    risk_limit = Column(JSON, comment='账户独立的风险限制配置，JSON格式')
    is_active = Column(Boolean, default=True, comment='账户是否激活可用')

    # 时间戳
    created_at = Column(DateTime, server_default=func.now(), comment='创建时间')
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment='更新时间')

    # 关系
    positions = relationship("Position", back_populates="account", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="account", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index('idx_account_exchange_type', 'exchange', 'account_type', 'is_active'),
        Index('idx_account_active', 'is_active'),
    )

    @validates('leverage')
    def validate_leverage(self, key, leverage):
        """验证杠杆倍数"""
        if self.account_type == AccountType.FUTURE and leverage < 1:
            raise ValueError("合约账户杠杆必须≥1")
        return leverage

    def __repr__(self):
        return f"<AssetAccount(id={self.id}, exchange={self.exchange}, type={self.account_type.value})>"


class TradingPair(Base):
    """
    交易对配置表 - 核心三级管理结构：基础符号-交易所-账户类型
    支持Web界面动态管理，支持多交易所同名交易对不同映射
    """
    __tablename__ = "trading_pair"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 三级管理结构
    base_symbol = Column(String(20), nullable=False, comment='系统统一基础符号，如: BTC/USDT')
    exchange = Column(String(20), nullable=False, comment='交易所标识')
    account_type = Column(Enum(AccountType), nullable=False, comment='账户类型')

    # 交易所原生符号（解决名称不一致问题）
    exchange_symbol = Column(String(30), nullable=False, comment='交易所原生符号，如: BTCUSDT, BTC-USDT')

    # 配置与状态
    is_enabled = Column(Boolean, default=True, comment='是否启用该交易对')
    config = Column(JSON, comment='交易对特有配置，JSON格式，如: { "min_qty": 0.001, "leverage": 10 }')

    # 元数据
    description = Column(String(255), comment='交易对描述')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    orders = relationship("Order", back_populates="trading_pair")

    # 唯一约束：确保同一交易对在同一交易所的现货和合约是独立记录
    __table_args__ = (
        UniqueConstraint('base_symbol', 'exchange', 'account_type',
                         name='uq_pair_exchange_account'),
        Index('idx_pair_enabled', 'is_enabled'),
        Index('idx_pair_exchange', 'exchange', 'account_type', 'is_enabled'),
        Index('idx_pair_search', 'base_symbol', 'exchange', 'account_type'),
    )

    def get_full_identifier(self) -> str:
        """获取完整标识符，用于日志和显示"""
        return f"{self.base_symbol}@{self.exchange}_{self.account_type.value}"

    def __repr__(self):
        return f"<TradingPair({self.get_full_identifier()}, enabled={self.is_enabled})>"


class ExecutionPolicy(Base):
    """
    执行策略表 - 定义信号如何执行，支持多交易所路由
    """
    __tablename__ = "execution_policy"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, comment='策略名称')

    # 多交易所模式开关
    multi_exchange_mode = Column(Boolean, default=False,
                                 comment='是否启用多交易所同时执行')

    # 目标交易对配置（JSON数组，存储trading_pair.id列表）
    target_pairs = Column(JSON, nullable=False,
                          comment='目标交易对ID列表，如: [1, 2, 3]')

    # 执行参数
    order_type = Column(Enum(OrderType), default=OrderType.MARKET,
                        comment='默认订单类型')
    time_in_force = Column(String(20), default='GTC', comment='订单有效期: GTC/IOC/FOK')

    # 限价回踩策略参数（当order_type为LIMIT时生效）
    limit_pullback_ratio = Column(DECIMAL(5, 4), default=0.005,
                                  comment='限价回踩比例（ATR倍数）')
    entry_timeout_seconds = Column(Integer, default=300,
                                   comment='入场超时时间（秒）')

    # 追价保护参数
    max_chase_atr_ratio = Column(DECIMAL(5, 4), default=0.3,
                                 comment='最大追价距离（ATR倍数）')

    # 状态
    is_active = Column(Boolean, default=True, comment='策略是否激活')

    # 元数据
    description = Column(Text, comment='策略详细描述')
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index('idx_policy_active', 'is_active'),
    )

    @validates('target_pairs')
    def validate_target_pairs(self, key, target_pairs):
        """验证目标交易对配置"""
        if not isinstance(target_pairs, list):
            raise ValueError("target_pairs必须是列表")
        if not target_pairs:
            raise ValueError("target_pairs不能为空")
        return target_pairs

    def __repr__(self):
        mode = "multi" if self.multi_exchange_mode else "single"
        return f"<ExecutionPolicy({self.name}, mode={mode}, targets={len(self.target_pairs)})>"


class TradingSignal(Base):
    """
    交易信号表 - 记录策略产生的原始信号，用于决策审计
    """
    __tablename__ = "trading_signal"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 信号源信息
    strategy_id = Column(String(50), nullable=False, comment='策略标识符')
    strategy_version = Column(String(20), comment='策略版本')

    # 信号目标
    base_symbol = Column(String(20), nullable=False, comment='基础交易对符号')

    # 信号内容
    action = Column(Enum(SignalAction), nullable=False, comment='信号动作')
    confidence = Column(DECIMAL(5, 4), comment='置信度 0-1')

    # 信号原因与上下文（关键审计字段）
    reasoning = Column(Text, comment='信号生成理由（文本描述）')
    metadata = Column(JSON, comment='信号元数据（指标快照、特征值等）')

    # 时间信息
    generated_at = Column(DateTime(6), nullable=False, comment='信号生成时间（高精度）')

    # 处理状态
    processed = Column(String(20), default='pending',
                       comment='处理状态: pending/accepted/rejected')
    reject_reason = Column(String(200), comment='拒绝原因（如果被拒绝）')

    # 审计时间戳
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    orders = relationship("Order", back_populates="signal")

    # 索引
    __table_args__ = (
        Index('idx_signal_strategy_time', 'strategy_id', 'generated_at'),
        Index('idx_signal_processed', 'processed', 'generated_at'),
        Index('idx_signal_symbol_time', 'base_symbol', 'generated_at'),
    )

    def __repr__(self):
        return f"<TradingSignal(id={self.id}, {self.base_symbol} {self.action.value}, conf={self.confidence})>"


class Order(Base):
    """
    订单表 - 记录订单全生命周期，包含完整的决策审计链
    核心审计表，必须包含完整的"为什么下单"信息
    """
    __tablename__ = "orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 订单标识
    client_order_id = Column(String(50), unique=True, nullable=False,
                             comment='系统生成的客户端订单ID')
    exchange_order_id = Column(String(100), comment='交易所返回的订单ID')

    # 关联关系
    trading_pair_id = Column(Integer, ForeignKey('trading_pair.id'), nullable=False)
    account_id = Column(String(50), ForeignKey('asset_account.id'), nullable=False)
    signal_id = Column(BigInteger, ForeignKey('trading_signal.id'), comment='关联的原始信号')

    # 订单基本信息
    symbol = Column(String(20), nullable=False, comment='交易对符号（系统基础符号）')
    side = Column(Enum(OrderSide), nullable=False)
    type = Column(Enum(OrderType), nullable=False)

    # 订单参数
    price = Column(DECIMAL(30, 12), comment='委托价格（限价单必需）')
    quantity = Column(DECIMAL(30, 12), nullable=False, comment='委托数量')

    # 成交信息
    filled_quantity = Column(DECIMAL(30, 12), default=0, comment='已成交数量')
    avg_fill_price = Column(DECIMAL(30, 12), comment='平均成交价')

    # 状态
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.NEW)

    # 【核心审计字段】决策链 - JSON格式，记录从信号到执行的完整决策过程
    decision_chain = Column(JSON, nullable=False,
                            comment='完整决策链，包含：信号详情、风控检查结果、路由决策、执行参数等')

    # 多交易所路由信息（如果是多所执行）
    routing_source = Column(String(50), comment='路由来源，如：master_signal_id 或 direct')

    # 手续费信息
    fee = Column(DECIMAL(30, 12), comment='手续费金额')
    fee_asset = Column(String(10), comment='手续费币种')

    # 时间戳
    created_at = Column(DateTime(6), server_default=func.now(6), comment='创建时间（高精度）')
    updated_at = Column(DateTime(6), server_default=func.now(6), onupdate=func.now(6),
                        comment='更新时间（高精度）')

    # 关系
    trading_pair = relationship("TradingPair", back_populates="orders")
    account = relationship("AssetAccount", back_populates="orders")
    signal = relationship("TradingSignal", back_populates="orders")
    trades = relationship("Trade", back_populates="order", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index('idx_order_client_id', 'client_order_id'),
        Index('idx_order_exchange_id', 'exchange_order_id'),
        Index('idx_order_status', 'status', 'created_at'),
        Index('idx_order_account', 'account_id', 'created_at'),
        Index('idx_order_signal', 'signal_id'),
        Index('idx_order_pair_time', 'trading_pair_id', 'created_at'),
    )

    def is_filled(self) -> bool:
        """检查订单是否完全成交"""
        return self.status == OrderStatus.FILLED

    def fill_percentage(self) -> float:
        """获取订单成交百分比"""
        if self.quantity == 0:
            return 0.0
        return float(self.filled_quantity / self.quantity)

    def __repr__(self):
        return f"<Order(id={self.id}, {self.symbol} {self.side.value} {self.type.value}, status={self.status.value})>"


class Trade(Base):
    """
    成交记录表 - 记录每笔成交明细，用于精确计算成本和盈亏
    """
    __tablename__ = "trades"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 关联订单
    order_id = Column(BigInteger, ForeignKey('orders.id'), nullable=False)

    # 成交标识
    exchange_trade_id = Column(String(100), nullable=False, comment='交易所成交ID')

    # 成交详情
    symbol = Column(String(20), nullable=False)
    side = Column(Enum(OrderSide), nullable=False)
    price = Column(DECIMAL(30, 12), nullable=False)
    quantity = Column(DECIMAL(30, 12), nullable=False)

    # 手续费
    fee = Column(DECIMAL(30, 12), comment='手续费金额')
    fee_asset = Column(String(10), comment='手续费币种')

    # 盈亏计算（平仓时更新）
    realized_pnl = Column(DECIMAL(30, 12), comment='已实现盈亏')
    pnl_asset = Column(String(10), comment='盈亏币种')

    # 时间信息
    traded_at = Column(DateTime(6), nullable=False, comment='交易所成交时间戳（高精度）')
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    order = relationship("Order", back_populates="trades")

    # 索引与约束
    __table_args__ = (
        UniqueConstraint('exchange_trade_id', name='uq_exchange_trade_id'),
        Index('idx_trade_order', 'order_id'),
        Index('idx_trade_time', 'traded_at'),
        Index('idx_trade_symbol_time', 'symbol', 'traded_at'),
    )

    def __repr__(self):
        return f"<Trade(id={self.id}, order={self.order_id}, {self.symbol} {self.side.value} {self.quantity}@{self.price})>"


class Position(Base):
    """
    仓位明细表 - 实时跟踪现货和合约持仓
    由系统主动维护，非交易所快照，支持多账户多交易对
    """
    __tablename__ = "positions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 关联账户
    account_id = Column(String(50), ForeignKey('asset_account.id'), nullable=False)

    # 仓位标识
    symbol = Column(String(20), nullable=False, comment='交易对符号（系统基础符号）')

    # 仓位方向（现货为LONG）
    direction = Column(Enum('LONG', 'SHORT'), default='LONG')

    # 仓位数量
    quantity = Column(DECIMAL(30, 12), default=0, comment='净持仓数量')

    # 成本与价格
    avg_open_price = Column(DECIMAL(30, 12), comment='平均开仓价')
    current_price = Column(DECIMAL(30, 12), comment='当前市价（最后更新）')

    # 盈亏计算
    unrealized_pnl = Column(DECIMAL(30, 12), default=0, comment='浮动盈亏')
    unrealized_pnl_percentage = Column(DECIMAL(10, 4), comment='浮动盈亏百分比')

    # 合约特有字段
    leverage = Column(Integer, comment='杠杆倍数（仅合约）')
    liquidation_price = Column(DECIMAL(30, 12), comment='强平价（仅合约）')
    margin = Column(DECIMAL(30, 12), comment='占用保证金（仅合约）')

    # 状态
    is_active = Column(Boolean, default=True, comment='仓位是否活跃')

    # 时间戳
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    account = relationship("AssetAccount", back_populates="positions")

    # 唯一约束：一个账户一个交易对一个方向只能有一条活跃仓位记录
    __table_args__ = (
        UniqueConstraint('account_id', 'symbol', 'direction', 'is_active',
                         name='uq_active_position'),
        Index('idx_position_account', 'account_id', 'is_active'),
        Index('idx_position_symbol', 'symbol', 'is_active'),
        Index('idx_position_active', 'is_active', 'updated_at'),
    )

    def update_pnl(self, current_price: Decimal) -> None:
        """更新仓位盈亏"""
        if self.quantity == 0 or not self.avg_open_price:
            self.unrealized_pnl = Decimal('0')
            self.unrealized_pnl_percentage = Decimal('0')
            return

        if self.direction == 'LONG':
            pnl = (current_price - self.avg_open_price) * self.quantity
        else:  # SHORT
            pnl = (self.avg_open_price - current_price) * self.quantity

        self.unrealized_pnl = pnl
        self.unrealized_pnl_percentage = (pnl / (self.avg_open_price * self.quantity)) * 100

    def __repr__(self):
        return f"<Position(account={self.account_id}, {self.symbol} {self.direction} {self.quantity}, pnl={self.unrealized_pnl})>"


class SecureConfig(Base):
    """
    加密配置表 - 安全存储所有API密钥和敏感配置
    替代传统的.env文件，支持Web界面管理
    """
    __tablename__ = "secure_config"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 配置分组
    group = Column(String(50), nullable=False, comment='配置分组，如：exchange, ai, telegram')
    key = Column(String(100), unique=True, nullable=False, comment='配置键名')

    # 配置值（加密存储）
    value = Column(Text, nullable=False, comment='配置值（密文）')
    is_encrypted = Column(Boolean, default=True, comment='是否已加密')

    # 元数据
    description = Column(String(255), comment='配置描述')
    version = Column(Integer, default=1, comment='配置版本（用于轮换）')

    # 时间戳
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 索引
    __table_args__ = (
        Index('idx_config_group', 'group'),
        Index('idx_config_key', 'key'),
    )

    def __repr__(self):
        return f"<SecureConfig(group={self.group}, key={self.key}, encrypted={self.is_encrypted})>"


class EventLog(Base):
    """
    事件日志表 - 记录所有关键业务事件
    用于业务分析、监控和审计
    """
    __tablename__ = "event_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 事件标识
    event_type = Column(String(50), nullable=False, comment='事件类型')
    event_subtype = Column(String(50), comment='事件子类型')

    # 关联资源
    resource_type = Column(String(50), comment='资源类型，如：order, signal, account')
    resource_id = Column(String(100), comment='资源ID')

    # 事件数据
    data = Column(JSON, comment='事件详细数据（JSON格式）')

    # 严重级别
    severity = Column(Enum(LogLevel), default=LogLevel.INFO, comment='事件严重级别')

    # 来源信息
    source_module = Column(String(50), comment='事件来源模块')
    source_function = Column(String(100), comment='事件来源函数')

    # 时间戳
    created_at = Column(DateTime(6), server_default=func.now(6), comment='事件创建时间（高精度）')

    # 索引
    __table_args__ = (
        Index('idx_event_type_time', 'event_type', 'created_at'),
        Index('idx_event_resource', 'resource_type', 'resource_id'),
        Index('idx_event_severity_time', 'severity', 'created_at'),
        Index('idx_event_module_time', 'source_module', 'created_at'),
    )

    def __repr__(self):
        return f"<EventLog(type={self.event_type}, resource={self.resource_type}:{self.resource_id}, severity={self.severity.value})>"


class SystemLog(Base):
    """
    系统运行日志表 - 记录程序运行日志
    用于调试、排错和系统监控
    """
    __tablename__ = "system_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 日志级别
    level = Column(Enum(LogLevel), nullable=False, comment='日志级别')

    # 日志来源
    logger_name = Column(String(100), nullable=False, comment='日志记录器名称')
    module = Column(String(100), comment='模块名')
    function = Column(String(100), comment='函数名')
    line_no = Column(Integer, comment='行号')

    # 日志内容
    message = Column(Text, nullable=False, comment='日志消息')
    exc_info = Column(Text, comment='异常信息（如果有）')

    # 上下文
    extra = Column(JSON, comment='额外上下文信息')

    # 时间戳
    created_at = Column(DateTime(6), server_default=func.now(6))

    # 索引
    __table_args__ = (
        Index('idx_log_level_time', 'level', 'created_at'),
        Index('idx_log_module_time', 'module', 'created_at'),
        Index('idx_log_logger_time', 'logger_name', 'created_at'),
    )

    def __repr__(self):
        return f"<SystemLog(level={self.level.value}, module={self.module}, message={self.message[:50]}...)>"


class AuditLog(Base):
    """
    操作审计日志表 - 记录所有人工操作
    用于安全审计和操作追溯
    """
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # 操作者信息
    user_identity = Column(String(50), nullable=False, comment='操作者身份：system, web_admin, telegram')
    user_ip = Column(String(45), comment='操作者IP地址')
    user_agent = Column(String(255), comment='用户代理')

    # 操作信息
    action = Column(String(100), nullable=False, comment='操作类型')
    resource_type = Column(String(50), comment='操作对象类型')
    resource_id = Column(String(100), comment='操作对象ID')

    # 操作详情
    details = Column(JSON, comment='操作详情与变更内容')
    status = Column(String(20), default='success', comment='操作状态：success/failed')
    error_message = Column(Text, comment='错误信息（如果失败）')

    # 时间戳
    created_at = Column(DateTime(6), server_default=func.now(6))

    # 索引
    __table_args__ = (
        Index('idx_audit_user_time', 'user_identity', 'created_at'),
        Index('idx_audit_action_time', 'action', 'created_at'),
        Index('idx_audit_resource', 'resource_type', 'resource_id', 'created_at'),
    )

    def __repr__(self):
        return f"<AuditLog(user={self.user_identity}, action={self.action}, status={self.status})>"


# 导出所有模型类
__all__ = [
    'Base',
    'AssetAccount',
    'TradingPair',
    'ExecutionPolicy',
    'TradingSignal',
    'Order',
    'Trade',
    'Position',
    'SecureConfig',
    'EventLog',
    'SystemLog',
    'AuditLog',
    'AccountType',
    'OrderSide',
    'OrderType',
    'OrderStatus',
    'SignalAction',
    'LogLevel',
]