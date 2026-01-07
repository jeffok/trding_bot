"""幂等键与 client_order_id 生成。

里程碑 A 的目标：
- client_order_id 必须对“同一交易机会/同一意图”的重试保持稳定；
- 长度必须满足常见交易所限制（通常 <= 64）。

约定：
- 对策略信号 BUY/SELL：使用最新 K 线 open_time_ms 作为机会锚点（同一根 K 内重试 id 不变）。
- 对止损/紧急退出：同样使用当根 K 线 open_time_ms 作为锚点（保证短期重试幂等）。

注意：
- 这里不引入 decision_records 表（那是后续里程碑），因此无法跨多根 K 线保持同一意图的 id。
  但对 MVP 来说：一旦成功成交会写 position_snapshots，下一轮就不会重复下单。
"""

from __future__ import annotations

import hashlib


def normalize_symbol(symbol: str) -> str:
    """把交易对转成可用于 client_order_id 的短格式。"""
    s = (symbol or "").upper().strip()
    # 常见形态：BTC/USDT、BTCUSDT、BTC-USDT
    for ch in ["/", "-", ":", " "]:
        s = s.replace(ch, "")
    return s


def make_client_order_id(
    action: str,
    symbol: str,
    *,
    kline_open_time_ms: int,
    strategy_tag: str = "sb",
    max_len: int = 64,
) -> str:
    """生成稳定的 client_order_id。

    参数：
    - action: buy/sell/sl/exit 等动作前缀
    - symbol: 交易对
    - kline_open_time_ms: 机会锚点（同一根 K 不变）
    - strategy_tag: 策略/版本标签，避免不同策略冲突
    """
    a = (action or "").lower().strip()
    sym = normalize_symbol(symbol)
    base = f"{a}_{strategy_tag}_{sym}_{int(kline_open_time_ms)}"
    if len(base) <= max_len:
        return base

    # 超长则做 hash 缩短，但保持可读的前缀
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    sym_short = sym[:10]
    short = f"{a}_{strategy_tag}_{sym_short}_{int(kline_open_time_ms)}_{h}"
    return short[:max_len]
