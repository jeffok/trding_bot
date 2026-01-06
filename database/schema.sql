-- database/schema.sql

-- 1. 系统配置表 (System Config)
CREATE TABLE IF NOT EXISTS system_config (
    key_name VARCHAR(64) PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at_hk DATETIME NOT NULL,
    updated_by VARCHAR(64) NOT NULL, -- actor
    version INT DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 配置审计表 (Config Audit) - V8.3 4.4.3
CREATE TABLE IF NOT EXISTS config_audit (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(64) NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT,
    actor VARCHAR(64) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    trace_id VARCHAR(64),
    created_at_hk DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 服务状态表 (Service Status)
CREATE TABLE IF NOT EXISTS service_status (
    service_name VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) NOT NULL, -- RUNNING, HALTED, ERROR
    last_heartbeat_hk DATETIME NOT NULL,
    metadata_json TEXT -- 包含 sync_lag, error_summary 等
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 控制指令表 (Control Commands) - V8.3 3.2.2 新增字段
CREATE TABLE IF NOT EXISTS control_commands (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    command_type VARCHAR(32) NOT NULL, -- HALT, RESUME, EMERGENCY
    params_json TEXT,
    status VARCHAR(32) DEFAULT 'PENDING', -- PENDING, PROCESSED, FAILED
    actor VARCHAR(64) NOT NULL,
    reason_code VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    trace_id VARCHAR(64),
    created_at_hk DATETIME NOT NULL,
    processed_at_hk DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 市场数据表 (Market Data) - V8.3 3.3 唯一键
CREATE TABLE IF NOT EXISTS market_data (
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    kline_open_ts_utc BIGINT NOT NULL, -- 毫秒时间戳
    open_price DECIMAL(20, 8) NOT NULL,
    high_price DECIMAL(20, 8) NOT NULL,
    low_price DECIMAL(20, 8) NOT NULL,
    close_price DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    created_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_market_data (symbol, timeframe, kline_open_ts_utc)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 市场数据缓存/指标 (Market Data Cache)
CREATE TABLE IF NOT EXISTS market_data_cache (
    symbol VARCHAR(32) NOT NULL,
    timeframe VARCHAR(8) NOT NULL,
    kline_open_ts_utc BIGINT NOT NULL,
    feature_version VARCHAR(16) NOT NULL DEFAULT 'v1',
    indicators_json JSON NOT NULL, -- 存储 ADX, EMA, Squeeze 等
    updated_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_cache (symbol, timeframe, kline_open_ts_utc, feature_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 订单事件流 (Order Events) - V8.3 2.1 & 3.2.1 核心表
CREATE TABLE IF NOT EXISTS order_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_order_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(32) NOT NULL, -- CREATED, SUBMITTED, FILLED, ERROR...
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL, -- BUY, SELL
    order_type VARCHAR(16) NOT NULL, -- MARKET, LIMIT
    quantity DECIMAL(20, 8),
    price DECIMAL(20, 8),

    -- V8.3 推荐新增字段
    trace_id VARCHAR(64),
    action VARCHAR(32),
    reason_code VARCHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(64) DEFAULT 'system',

    raw_payload_json TEXT, -- 脱敏后的原始响应
    event_ts_utc BIGINT NOT NULL, -- 事件发生时的 UTC 时间戳
    event_ts_hk DATETIME, -- 辅助查询字段

    created_at_utc DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_client_order (client_order_id),
    INDEX idx_symbol_ts (symbol, event_ts_utc),
    INDEX idx_trace (trace_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. 交易日志 (Trade Logs) - V8.3 3.2.3 新增字段
CREATE TABLE IF NOT EXISTS trade_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    client_order_id VARCHAR(64) NOT NULL,
    exchange_order_id VARCHAR(64),
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL,
    fill_price DECIMAL(20, 8) NOT NULL,
    fill_quantity DECIMAL(20, 8) NOT NULL,
    fee DECIMAL(20, 8),
    fee_asset VARCHAR(16),

    -- 只有平仓时填写
    realized_pnl DECIMAL(20, 8),
    close_reason_code VARCHAR(64),
    close_reason TEXT,

    executed_at_utc BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 持仓快照 (Position Snapshots)
CREATE TABLE IF NOT EXISTS position_snapshots (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    entry_price DECIMAL(20, 8) NOT NULL,
    unrealized_pnl DECIMAL(20, 8),
    leverage INT DEFAULT 1,
    margin_type VARCHAR(16) DEFAULT 'ISOLATED', -- 强制逐仓
    snapshot_ts_utc BIGINT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 归档审计 (Archive Audit)
CREATE TABLE IF NOT EXISTS archive_audit (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    table_name VARCHAR(64) NOT NULL,
    cutoff_ts_utc BIGINT NOT NULL,
    rows_moved INT NOT NULL,
    status VARCHAR(16) NOT NULL, -- SUCCESS, FAILED
    trace_id VARCHAR(64),
    created_at_hk DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;