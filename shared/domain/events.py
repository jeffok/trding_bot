"""Append-only order event writer (idempotent)."""

from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any, Dict, Optional

from ..db.maria import MariaDB
from .enums import OrderEventType, ReasonCode


def _json_default(o: Any) -> Any:
    """json.dumps 的兜底：解决 Decimal / datetime 等不可序列化对象。"""
    if isinstance(o, (datetime.datetime, datetime.date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        try:
            return float(o)
        except Exception:
            return str(o)
    return str(o)


def append_order_event(
    db: MariaDB,
    *,
    trace_id: str,
    service: str,
    exchange: str,
    symbol: str,
    client_order_id: str,
    exchange_order_id: Optional[str],
    event_type: OrderEventType,
    side: str,
    qty: float,
    price: Optional[float],
    status: str,
    reason_code: ReasonCode,
    reason: str,
    payload: Dict[str, Any],
) -> None:
    sql = """
    INSERT INTO order_events(
      trace_id, service, exchange, symbol, client_order_id, exchange_order_id,
      event_type, side, qty, price, status, reason_code, reason, payload_json
    ) VALUES (
      %s,%s,%s,%s,%s,%s,
      %s,%s,%s,%s,%s,%s,%s,%s
    )
    """
    # ✅ 修复：payload 里可能包含 Decimal/datetime，必须可序列化
    payload_json = json.dumps(payload or {}, ensure_ascii=False, default=_json_default)

    params = (
        trace_id,
        service,
        exchange,
        symbol,
        client_order_id,
        exchange_order_id,
        event_type.value,
        side,
        float(qty),
        float(price) if price is not None else None,
        status,
        reason_code.value,
        reason,
        payload_json,
    )
    try:
        db.execute(sql, params)
    except Exception as e:
        msg = str(e).lower()
        # 幂等：同一个 (exchange, symbol, client_order_id, event_type) 只允许写一次。
        # 兼容历史索引名：uq_client_order（旧）/ uq_client_order_event（新）。
        if "duplicate" in msg and ("uq_client_order_event" in msg or "uq_client_order" in msg):
            return
        raise
