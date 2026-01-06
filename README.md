# Alpha-Sniper-V8（B-lite）

本仓库实现 **B-lite 架构**（三服务），用于构建可长期运行、可审计、可观测的多币种逐仓量化交易系统。

---

## 架构概览

包含三个服务：

- **strategy-engine（策略引擎）**  
  信号计算 → 风控校验 → 订单执行 → 成交对账 → 审计落库（事件流/快照/交易日志）

- **data-syncer（数据同步）**  
  K 线同步与补洞 → 清洗标准化 → 指标/特征预计算缓存 → 自动归档（热数据 90 天）

- **api-service（控制面）**  
  健康检查（汇总）/指标（Prometheus）/管理接口（热配置、停开仓、一键清仓）+ Telegram 告警

---

## 前置条件

你已经具备：

- 独立部署的 **MariaDB**
- 独立部署的 **Redis**

说明：

- 本项目 **不会安装 MariaDB/Redis**，只会通过环境变量连接你已有的服务。
- MariaDB 用户需要对目标库具有 **CREATE / ALTER / INDEX / INSERT / UPDATE / SELECT** 等权限（用于自动迁移与运行时写入）。

---

## 配置说明

### 1）环境变量文件

将 `.env.example` 复制为 `.env`，按需填写以下关键项：

- `DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD`
- `REDIS_URL`
- `EXCHANGE_NAME`（默认 `binance_um`）
- `BINANCE_API_KEY / BINANCE_API_SECRET / BINANCE_BASE_URL`
- `SYMBOLS`（例如：`BTCUSDT,ETHUSDT`）
- `TIMEFRAME`（默认 `15m`）
- `ENABLE_TRADING`（`true/false`）
- `PAPER_TRADING`（`true/false`）
- `ADMIN_BEARER_TOKEN`（api-service 管理接口鉴权）

### 2）数据库自动迁移（非常重要）

所有服务启动时都会自动执行 SQL 迁移（幂等）：

- 用于创建/升级数据库表结构
- 已执行过的迁移会被记录，重复启动不会重复执行同一迁移文件

---

## 启动方式

### 1）构建并启动

```bash
docker compose up -d --build
```

### 2）查看服务日志（示例）

```bash
docker logs -f asv8_strategy_engine
docker logs -f asv8_data_syncer
docker logs -f asv8_api_service
```

---

## 管理接口（api-service）

### 接口列表

- `GET /health`：查看三服务健康状态（基于心跳/状态汇总）
- `GET /metrics`：Prometheus 指标输出
- `POST /admin/update_config`：热更新系统参数（写入 system_config 并审计）
- `POST /admin/emergency_exit`：一键清仓并停止开仓（写入控制指令，由策略引擎执行）
- `POST /admin/halt`：停止开仓（不影响已持仓的减仓/平仓）
- `POST /admin/resume`：恢复开仓
- `GET /admin/status`：查看权益、持仓、最近订单、风控状态等摘要

### 鉴权方式

所有 `/admin/*` 接口都需要请求头：

```text
Authorization: Bearer <ADMIN_BEARER_TOKEN>
```

---

## 数据与审计（核心表）

系统会使用以下表实现审计与可回放：

- `order_events`：订单全生命周期事件流（不可变，含交易所原始回包脱敏存证）
- `position_snapshots`：持仓快照（每 5 分钟 + 关键事件触发）
- `trade_logs`：交易日志（用于统计与 AI 训练标签）
- `market_data`：原始 K 线数据（清洗后落库）
- `market_data_cache`：预计算特征缓存（ADX/EMA/Squeeze/Vol_Ratio 等）
- `service_status`：服务心跳与状态
- `control_commands`：控制指令（HALT/RESUME/EMERGENCY_EXIT/UPDATE_CONFIG）
- `system_config`：热更新配置
- `config_audit`：配置变更审计
- `ai_models`：AI 模型版本与二进制存储

---

## 运行建议

### 1）建议先纸面验证（强烈建议）

首次运行建议：

- `PAPER_TRADING=true`
- `ENABLE_TRADING=true`

待逻辑与审计链路验证完成后，再切换为实盘。

### 2）风控与自愈说明

- 策略引擎下单前执行硬风控校验：保证金地板、强平距离、风险预算（3%）等
- 发生连续失败/异常行情/回撤阈值等情况会触发停开仓（HALT），并通过告警通知
- 服务异常可通过容器重启恢复；数据同步与策略执行隔离（B-lite 的关键优势）

---

## 重要说明

- 本项目重点在“工程可长期运行”：幂等、审计、可观测性、自愈与可回放。
- 交易有风险，任何策略与系统都不保证盈利。请在可承受风险范围内使用。
