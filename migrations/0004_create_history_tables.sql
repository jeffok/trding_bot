-- 0004_create_history_tables.sql
-- Purpose: create *_history tables for daily archival (cutoff ~90d) + keep archive_audit as evidence.
-- Notes:
--   - history tables are append-only; archival job uses INSERT IGNORE + DELETE.
--   - archived_at is the time the row was moved to history.

CREATE TABLE IF NOT EXISTS market_data_history (
  symbol VARCHAR(32) NOT NULL,
  interval_minutes INT NOT NULL,
  open_time_ms BIGINT NOT NULL,
  close_time_ms BIGINT NOT NULL,
  open_price DECIMAL(28, 12) NOT NULL,
  high_price DECIMAL(28, 12) NOT NULL,
  low_price DECIMAL(28, 12) NOT NULL,
  close_price DECIMAL(28, 12) NOT NULL,
  volume DECIMAL(28, 12) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (symbol, interval_minutes, open_time_ms),
  INDEX idx_market_data_hist_close_time (symbol, interval_minutes, close_time_ms),
  INDEX idx_market_data_hist_archived_at (archived_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS order_events_history (
  id BIGINT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  trace_id VARCHAR(64) NOT NULL,
  service VARCHAR(64) NOT NULL,
  exchange VARCHAR(16) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  client_order_id VARCHAR(64) NOT NULL,
  exchange_order_id VARCHAR(64) NULL,
  event_type VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL,
  qty DECIMAL(28, 12) NOT NULL,
  price DECIMAL(28, 12) NULL,
  status VARCHAR(32) NOT NULL,
  reason_code VARCHAR(64) NOT NULL,
  reason TEXT NOT NULL,
  payload_json JSON NOT NULL,
  archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_order_events_hist_symbol_time (symbol, created_at),
  INDEX idx_order_events_hist_exchange_id (exchange, exchange_order_id),
  INDEX idx_order_events_hist_archived_at (archived_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS trade_logs_history (
  id BIGINT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  trace_id VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  side VARCHAR(8) NOT NULL,
  qty DECIMAL(28, 12) NOT NULL,
  entry_price DECIMAL(28, 12) NULL,
  exit_price DECIMAL(28, 12) NULL,
  pnl DECIMAL(28, 12) NULL,
  features_json JSON NOT NULL,
  label INT NULL,
  archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_trade_logs_hist_symbol_time (symbol, created_at),
  INDEX idx_trade_logs_hist_archived_at (archived_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS position_snapshots_history (
  id BIGINT PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  base_qty DECIMAL(28, 12) NOT NULL,
  avg_entry_price DECIMAL(28, 12) NULL,
  meta_json JSON NOT NULL,
  archived_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_position_hist_symbol_time (symbol, created_at),
  INDEX idx_position_hist_archived_at (archived_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
