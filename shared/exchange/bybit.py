from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .base import ExchangeClient
from .errors import AuthError, ExchangeError, RateLimitError, TemporaryError
from .rate_limiter import AdaptiveRateLimiter
from .types import Kline, OrderResult


def _now_ms() -> int:
    return int(time.time() * 1000)


class BybitV5LinearClient(ExchangeClient):
    """Bybit V5 USDT 合约（linear，逐仓）客户端。

    重点：
    - category=linear（USDT perpetual / futures）
    - 启动时：tradeMode=1（isolated margin） + buy/sell leverage
    - 平仓（Sell）后：通过 /v5/position/closed-pnl 查询 orderId 对应的 closedPnl（已包含手续费项），得到真实净盈亏
    """

    name = "bybit"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_secret: str,
        recv_window: int,
        leverage: int,
        position_idx: int,
        limiter: AdaptiveRateLimiter,
        metrics=None,
        service_name: str = "unknown",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret.encode("utf-8") if api_secret else b""
        self.recv_window = int(recv_window)
        self.leverage = int(leverage)
        self.position_idx = int(position_idx)

        self.limiter = limiter
        self.metrics = metrics
        self.service_name = service_name

        self.limiter.ensure_budget("bybit_public", 10, 10)
        self.limiter.ensure_budget("bybit_private", 5, 5)

        self._prepared_symbols: set[str] = set()

    # -------------------------
    # Bybit V5 签名
    # -------------------------
    def _sign(self, payload: str, ts_ms: int) -> str:
        pre = f"{ts_ms}{self.api_key}{self.recv_window}{payload}"
        return hmac.new(self.api_secret, pre.encode("utf-8"), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        signed: bool,
        budget: str,
    ) -> Any:
        url = f"{self.base_url}{path}"
        self.limiter.acquire(budget, 1.0)

        params = params or {}
        headers = {"Accept": "application/json"}

        if signed:
            if not self.api_key or not self.api_secret:
                raise AuthError("Missing Bybit API key/secret")

            ts = _now_ms()

            if method.upper() == "GET":
                # payload 为 query string（按 key 排序）
                qs = "&".join([f"{k}={params[k]}" for k in sorted(params.keys())])
                payload = qs
            else:
                payload = json.dumps(json_body or {}, separators=(",", ":"), ensure_ascii=False)

            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": str(ts),
                    "X-BAPI-RECV-WINDOW": str(self.recv_window),
                    "X-BAPI-SIGN": self._sign(payload, ts),
                    "Content-Type": "application/json",
                }
            )

        start = time.time()
        try:
            with httpx.Client(timeout=10) as client:
                if method.upper() == "GET":
                    resp = client.get(url, params=params, headers=headers)
                else:
                    resp = client.request(method, url, params=params, headers=headers, json=json_body)

            if resp.status_code in (429,):
                self.limiter.backoff(budget, 2.0)
                raise RateLimitError(resp.text[:200])
            if resp.status_code in (401, 403):
                raise AuthError(resp.text[:200])
            if resp.status_code >= 500:
                raise TemporaryError(resp.text[:200])
            if resp.status_code >= 400:
                raise ExchangeError(resp.text[:200])

            data = resp.json()

            # Bybit V5: retCode != 0 视为业务错误
            if isinstance(data, dict) and data.get("retCode") not in (0, "0", None):
                raise ExchangeError(f"{data.get('retMsg')} (retCode={data.get('retCode')})")

            return data
        except httpx.TimeoutException as e:
            raise TemporaryError(str(e)) from e
        finally:
            _ = start  # reserved

    # -------------------------
    # 逐仓 + 杠杆（一次性准备）
    # -------------------------
    def _ensure_isolated_and_leverage(self, symbol: str) -> None:
        if symbol in self._prepared_symbols:
            return

        # 逐仓 + 杠杆：/v5/position/switch-isolated
        # tradeMode: 0-cross, 1-isolated （Bybit API Explorer）
        try:
            self._request(
                "POST",
                "/v5/position/switch-isolated",
                json_body={
                    "category": "linear",
                    "symbol": symbol,
                    "tradeMode": 1,
                    "buyLeverage": str(self.leverage),
                    "sellLeverage": str(self.leverage),
                },
                signed=True,
                budget="bybit_private",
            )
        except ExchangeError:
            # 账户/币对不支持等情况，不阻塞主循环
            pass

        self._prepared_symbols.add(symbol)

    # -------------------------
    # 行情
    # -------------------------
    def fetch_klines(self, *, symbol: str, interval_minutes: int, start_ms: Optional[int], limit: int = 1000) -> List[Kline]:
        params: Dict[str, Any] = {
            "category": "linear",
            "symbol": symbol,
            "interval": str(int(interval_minutes)),
            "limit": int(limit),
        }
        if start_ms is not None:
            params["start"] = int(start_ms)

        data = self._request("GET", "/v5/market/kline", params=params, signed=False, budget="bybit_public")

        # 返回结构：result -> list
        rows = (((data or {}).get("result") or {}).get("list") or [])
        out: List[Kline] = []
        for row in rows:
            # row: [openTime, open, high, low, close, volume, turnover]
            out.append(
                Kline(
                    open_time_ms=int(row[0]),
                    close_time_ms=int(row[0]) + int(interval_minutes) * 60_000,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )
        # Bybit 返回倒序，这里改为时间升序，方便后续计算
        out.sort(key=lambda k: k.open_time_ms)
        return out

    # -------------------------
    # 下单 / 查询
    # -------------------------
    def place_market_order(self, *, symbol: str, side: str, qty: float, client_order_id: str) -> OrderResult:
        side_u = side.upper()
        if side_u not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side={side}")

        self._ensure_isolated_and_leverage(symbol)

        payload = {
            "category": "linear",
            "symbol": symbol,
            "side": "Buy" if side_u == "BUY" else "Sell",
            "orderType": "Market",
            "qty": str(qty),
            "timeInForce": "GTC",
            "orderLinkId": client_order_id,
        }

        # reduceOnly：SELL（平仓）更安全
        if side_u == "SELL":
            payload["reduceOnly"] = True

        # positionIdx：默认 0（One-way 模式）。如果你的账户是 Hedge 模式，需要改 BYBIT_POSITION_IDX
        if self.position_idx:
            payload["positionIdx"] = int(self.position_idx)

        data = self._request("POST", "/v5/order/create", json_body=payload, signed=True, budget="bybit_private")

        result = (data or {}).get("result") or {}
        order_id = str(result.get("orderId", ""))
        status = "NEW"  # 创建后马上去查状态
        filled_qty = 0.0

        # 查询直到 Filled（最多 10 秒）
        end = time.time() + 10
        last_order_raw = None
        while time.time() < end:
            st = self.get_order_status(symbol=symbol, client_order_id=client_order_id, exchange_order_id=order_id)
            status = st.status
            filled_qty = st.filled_qty
            last_order_raw = st.raw
            if status.upper() in ("FILLED", "FILLED_PARTIALLY", "PARTIALLY_FILLED", "CANCELED", "REJECTED"):
                break
            # Bybit realtime 订单状态可能为 New/Filled/Cancelled 等
            if status.upper() == "FILLED":
                break
            time.sleep(0.2)

        # 计算结算后的真实 pnl / fee
        fee_usdt, pnl_usdt = self._fetch_closed_pnl(symbol=symbol, order_id=order_id, side=side_u)

        # 尝试从 realtime 里取 avgPrice（不同账户类型字段可能不同）
        avg_price = None
        if isinstance(last_order_raw, dict):
            try:
                ap = (((last_order_raw.get("result") or {}).get("list") or [{}])[0]).get("avgPrice")
                if ap not in (None, "", "0", 0):
                    avg_price = float(ap)
            except Exception:
                avg_price = None

        return OrderResult(
            exchange_order_id=order_id,
            status=status,
            filled_qty=filled_qty,
            avg_price=avg_price,
            fee_usdt=fee_usdt,
            pnl_usdt=pnl_usdt,
            raw=data if isinstance(data, dict) else {"raw": data},
        )

    def get_order_status(self, *, symbol: str, client_order_id: str, exchange_order_id: Optional[str]) -> OrderResult:
        params: Dict[str, Any] = {"category": "linear", "symbol": symbol}
        if exchange_order_id:
            params["orderId"] = exchange_order_id
        else:
            params["orderLinkId"] = client_order_id

        data = self._request("GET", "/v5/order/realtime", params=params, signed=True, budget="bybit_private")
        lst = (((data or {}).get("result") or {}).get("list") or [])
        if not lst:
            return OrderResult(exchange_order_id=exchange_order_id or "", status="UNKNOWN", filled_qty=0.0, raw=data)

        o = lst[0]
        status = str(o.get("orderStatus", "UNKNOWN"))
        # cumExecQty: 已成交数量
        try:
            filled_qty = float(o.get("cumExecQty", "0") or 0.0)
        except Exception:
            filled_qty = 0.0

        return OrderResult(
            exchange_order_id=str(o.get("orderId", exchange_order_id or "")),
            status=status,
            filled_qty=filled_qty,
            avg_price=None,
            raw=data,
        )

    # -------------------------
    # 平仓结算 -> closedPnl（净值）
    # -------------------------
    def _fetch_closed_pnl(self, *, symbol: str, order_id: str, side: str) -> Tuple[Optional[float], Optional[float]]:
        """返回 (fee_usdt, pnl_usdt)。只在 SELL（平仓）时返回 pnl。

        Bybit 的 closed-pnl 返回：
        - closedPnl：Closed PnL（通常为净值）
        - openFee / closeFee：开/平仓手续费
        这里：
        - fee_usdt = |openFee| + |closeFee|（能取到就取）
        - pnl_usdt = closedPnl（SELL 时），保留 2 位小数
        """

        if side != "SELL":
            return None, 0.0

        deadline = time.time() + 12
        # 取近 15 分钟窗口：避免错过记录
        end_ms = _now_ms()
        start_ms = end_ms - 15 * 60_000

        while time.time() < deadline:
            try:
                data = self._request(
                    "GET",
                    "/v5/position/closed-pnl",
                    params={
                        "category": "linear",
                        "symbol": symbol,
                        "startTime": str(start_ms),
                        "endTime": str(end_ms),
                        "limit": "50",
                    },
                    signed=True,
                    budget="bybit_private",
                )
            except ExchangeError:
                data = None

            lst = (((data or {}).get("result") or {}).get("list") or [])
            for row in lst:
                if str(row.get("orderId", "")) == str(order_id):
                    # 真实净盈亏
                    pnl = None
                    try:
                        pnl = round(float(row.get("closedPnl", "0") or 0.0), 2)
                    except Exception:
                        pnl = None

                    # 手续费（如果能拿到）
                    fee = None
                    try:
                        of = float(row.get("openFee", "0") or 0.0)
                        cf = float(row.get("closeFee", "0") or 0.0)
                        fee = round(abs(of) + abs(cf), 2)
                    except Exception:
                        fee = None

                    return fee, pnl

            time.sleep(0.3)

        return None, None
