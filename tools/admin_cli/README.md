
# Admin CLI

这是一个轻量“管理小工具”，用于不依赖 API 的情况下做运维/回归检查。

## 当前功能

- `status`：打印 `system_config` 全部键值（以及更新时间）
- `halt --reason ...`：设置 `HALT_TRADING=true`（并写入 config_audit + 可选 Telegram）
- `resume --reason ...`：设置 `HALT_TRADING=false`（并写入 config_audit + 可选 Telegram）
- `emergency-exit --reason ...`：设置 `EMERGENCY_EXIT=true`（并写入 config_audit + 可选 Telegram）
- `smoke-test`：一键回归/冒烟测试（DB/Redis/表结构/数据管道/幂等/可选 E2E emergency_exit）

## 使用

在项目根目录（容器内或本机 Python 环境）：

```bash
python -m tools.admin_cli status
python -m tools.admin_cli halt --reason "maintenance"
python -m tools.admin_cli resume --reason "ok"
python -m tools.admin_cli emergency-exit --reason "test"
python -m tools.admin_cli smoke-test
```

> 注意：`smoke-test` 的最后一步 `emergency_exit_e2e` 需要 `strategy-engine` 正在运行并且 tick 周期足够短。
