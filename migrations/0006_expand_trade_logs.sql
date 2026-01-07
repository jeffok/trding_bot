-- 0006_expand_trade_logs.sql
-- Milestone E: trade_logs full lifecycle fields (OPEN/CLOSED), stop-loss consistency, AI metadata.

ALTER TABLE trade_logs
  ADD COLUMN status VARCHAR(16) NULL AFTER label,
  ADD COLUMN updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER status,
  ADD COLUMN actor VARCHAR(64) NULL AFTER trace_id,
  ADD COLUMN leverage INT NULL AFTER qty,
  ADD COLUMN stop_dist_pct DECIMAL(28, 12) NULL AFTER leverage,
  ADD COLUMN stop_price DECIMAL(28, 12) NULL AFTER stop_dist_pct,
  ADD COLUMN client_order_id VARCHAR(64) NULL AFTER stop_price,
  ADD COLUMN exchange_order_id VARCHAR(128) NULL AFTER client_order_id,
  ADD COLUMN robot_score DECIMAL(28, 12) NULL AFTER exchange_order_id,
  ADD COLUMN ai_prob DECIMAL(28, 12) NULL AFTER robot_score,
  ADD COLUMN open_reason_code VARCHAR(64) NULL AFTER ai_prob,
  ADD COLUMN open_reason TEXT NULL AFTER open_reason_code,
  ADD COLUMN close_reason_code VARCHAR(64) NULL AFTER open_reason,
  ADD COLUMN close_reason TEXT NULL AFTER close_reason_code,
  ADD COLUMN entry_time_ms BIGINT NULL AFTER close_reason,
  ADD COLUMN exit_time_ms BIGINT NULL AFTER entry_time_ms;

CREATE INDEX idx_trade_logs_symbol_status_time ON trade_logs(symbol, status, created_at);

ALTER TABLE trade_logs_history
  ADD COLUMN status VARCHAR(16) NULL AFTER label,
  ADD COLUMN actor VARCHAR(64) NULL AFTER trace_id,
  ADD COLUMN leverage INT NULL AFTER qty,
  ADD COLUMN stop_dist_pct DECIMAL(28, 12) NULL AFTER leverage,
  ADD COLUMN stop_price DECIMAL(28, 12) NULL AFTER stop_dist_pct,
  ADD COLUMN client_order_id VARCHAR(64) NULL AFTER stop_price,
  ADD COLUMN exchange_order_id VARCHAR(128) NULL AFTER client_order_id,
  ADD COLUMN robot_score DECIMAL(28, 12) NULL AFTER exchange_order_id,
  ADD COLUMN ai_prob DECIMAL(28, 12) NULL AFTER robot_score,
  ADD COLUMN open_reason_code VARCHAR(64) NULL AFTER ai_prob,
  ADD COLUMN open_reason TEXT NULL AFTER open_reason_code,
  ADD COLUMN close_reason_code VARCHAR(64) NULL AFTER open_reason,
  ADD COLUMN close_reason TEXT NULL AFTER close_reason_code,
  ADD COLUMN entry_time_ms BIGINT NULL AFTER close_reason,
  ADD COLUMN exit_time_ms BIGINT NULL AFTER entry_time_ms;
