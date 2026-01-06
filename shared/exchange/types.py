from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Kline:
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class OrderResult:
    """统一订单结果结构（跨交易所）。

    说明：
    - pnl_usdt：建议理解为“订单结算后的净盈亏（USDT）”，即尽量已扣除交易手续费（以及交易所能归集到订单/平仓记录里的相关费用）。
      * 对于 BUY（开仓）通常为 0 或 None
      * 对于 SELL（平仓/止损/紧急退出）应优先从交易所“成交/结算记录”获取真实值，而不是用 (price-entry)*qty 公式推算
    - fee_usdt：如果交易所返回可用手续费信息，则写入；否则为 None
    """

    exchange_order_id: str
    status: str
    filled_qty: float

    avg_price: Optional[float] = None
    fee_usdt: Optional[float] = None
    pnl_usdt: Optional[float] = None

    raw: Optional[dict] = None
