from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
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

    !!! 重要（解决 retCode=10004）：
    Bybit v5 签名要求 “签名明文” 与 “实际发出的请求内容” 完全一致：
    - GET：签名用的 queryString 必须与实际 URL 的 queryString 完全一致（包括参数顺序/编码）
    - POST：签名用的 jsonBodyString 必须与实际发送的 body 字符串完全一致（空格/换行/键顺序都影响）
    因此本实现：
    - GET：用同一份 list[tuple] 构造 queryString，并把同样顺序的 params 交给 httpx
    - POST：先生成紧凑 JSON 字符串用于签名，同时用 content= 原样发送（不用 httpx 的 json= 重新序列化）
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
        # v5: prehash = timestamp + api_key + recv_window + payload(queryString or jsonBodyString)
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

        # 为了避免签名明文与实际发送内容不一致：
        # - GET：使用同一份 params 顺序来构造 queryString，并把同样顺序的 params 传给 httpx
        # - POST：用同一份 JSON 字符串作为签名明文，并以 raw content 发送（不要用 httpx 的 json= 让它重新序列化）
        send_params: Any = params
        signed_payload: Optional[str] = None
        content_bytes: Optional[bytes] = None

        if signed:
            if not self.api_key or not self.api_secret:
                raise AuthError("Missing Bybit API key/secret")

            ts = _now_ms()

            if method.upper() == "GET":
                # payload 为 query string（必须与实际请求的 queryString 完全一致）
                items = [(k, params[k]) for k in sorted(params.keys())]
                signed_payload = urlencode(items, doseq=True)
                send_params = items  # httpx 会按 list[tuple] 的顺序拼接 query
            else:
                signed_payload = json.dumps(json_body or {}, separators=(",", ":"), ensure_ascii=False)
                content_bytes = signed_payload.encode("utf-8")

            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": str(ts),
                    "X-BAPI-RECV-WINDOW": str(self.recv_window),
                    "X-BAPI-SIGN": self._sign(signed_payload or "", ts),
                    "Content-Type": "application/json",
                }
            )

        start = time.time()
        try:
            with httpx.Client(timeout=10) as client:
                if method.upper() == "GET":
                    resp = client.get(url, params=send_params, headers=headers)
                else:
                    if content_bytes is not None:
                        # ✅ 用与签名一致的 JSON 字符串原样发送
                        resp = client.request(method, url, params=send_params, headers=headers, content=content_bytes)
                    else:
                        resp = client.request(method, url, params=send_params, headers=headers, json=json_body)

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

        data = self._request("POST", "/v5/order/create", json_body=payload, signed=True, budget="bybit_private")
        result = (data or {}).get("result") or {}
        oid = result.get("orderId") or ""
        return OrderResult(exchange_order_id=str(oid), raw=data)

    def get_order(self, *, symbol: str, order_id: str) -> Dict[str, Any]:
        params = {"category": "linear", "symbol": symbol, "orderId": order_id}
        data = self._request("GET", "/v5/order/realtime", params=params, signed=True, budget="bybit_private")
        return data

    def cancel_order(self, *, symbol: str, order_id: str) -> Dict[str, Any]:
        payload = {"category": "linear", "symbol": symbol, "orderId": order_id}
        data = self._request("POST", "/v5/order/cancel", json_body=payload, signed=True, budget="bybit_private")
        return data

    # -------------------------
    # 平仓后真实 PnL（包含手续费）：
    # /v5/position/closed-pnl?category=linear&symbol=...&orderId=...
    # -------------------------
    def fetch_closed_pnl_usdt(self, *, symbol: str, order_id: str) -> Optional[float]:
        params = {"category": "linear", "symbol": symbol, "orderId": order_id}

        # closed-pnl 有一定延迟，因此这里做短轮询
        end = time.time() + 10
        last_err: Optional[str] = None
        while time.time() < end:
            try:
                data = self._request("GET", "/v5/position/closed-pnl", params=params, signed=True, budget="bybit_private")
                rows = (((data or {}).get("result") or {}).get("list") or [])
                if not rows:
                    time.sleep(0.5)
                    continue

                row = rows[0]
                # closedPnl 已是净值（含手续费影响），可能是字符串
                v = row.get("closedPnl")
                if v is None:
                    time.sleep(0.5)
                    continue

                try:
                    return float(v)
                except Exception:
                    return None
            except Exception as e:
                last_err = str(e)
                time.sleep(0.5)

        _ = last_err
        return None

    # -------------------------
    # 资金 / 仓位（可选工具用）
    # -------------------------
    def get_wallet_balance(self) -> Dict[str, Any]:
        # Bybit v5 钱包余额（统一账户可能需要 accountType 参数）
        params: Dict[str, Any] = {"accountType": "UNIFIED"}
        data = self._request("GET", "/v5/account/wallet-balance", params=params, signed=True, budget="bybit_private")
        return data

    # -------------------------
    # ExchangeClient 接口实现
    # -------------------------
    def set_leverage_and_margin_mode(self, *, symbol: str, leverage: int) -> None:
        self.leverage = int(leverage)
        self._prepared_symbols.discard(symbol)
        self._ensure_isolated_and_leverage(symbol)

    def wait_order_filled(self, *, symbol: str, order_id: str, timeout_seconds: int = 12) -> Dict[str, Any]:
        deadline = time.time() + timeout_seconds
        last: Optional[Dict[str, Any]] = None
        while time.time() < deadline:
            data = self.get_order(symbol=symbol, order_id=order_id)
            rows = (((data or {}).get("result") or {}).get("list") or [])
            if rows:
                last = rows[0]
                status = str(last.get("orderStatus") or "").lower()
                if status in ("filled", "partiallyfilled", "partialfilled"):
                    return last
                if status in ("cancelled", "rejected"):
                    return last
            time.sleep(0.4)
        return last or {}

    def normalize_order_fill(self, raw: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        """
        返回：(avg_price, filled_qty)
        Bybit realtime 返回字段可能为 avgPrice / cumExecQty / cumExecValue 等，尽量兼容。
        """
        if not raw:
            return None, None

        avg_price = raw.get("avgPrice") or raw.get("avg_price") or raw.get("price")
        filled_qty = raw.get("cumExecQty") or raw.get("cum_exec_qty") or raw.get("qty")

        try:
            ap = float(avg_price) if avg_price is not None else None
        except Exception:
            ap = None

        try:
            fq = float(filled_qty) if filled_qty is not None else None
        except Exception:
            fq = None

        return ap, fq

    def place_and_wait_filled(
        self, *, symbol: str, side: str, qty: float, client_order_id: str, timeout_seconds: int = 12
    ) -> OrderResult:
        r = self.place_market_order(symbol=symbol, side=side, qty=qty, client_order_id=client_order_id)
        if r.exchange_order_id:
            raw = self.wait_order_filled(symbol=symbol, order_id=r.exchange_order_id, timeout_seconds=timeout_seconds)
            r.raw = raw or r.raw
        return r


def make_bybit_client(
    *,
    base_url: str,
    api_key: str,
    api_secret: str,
    recv_window: int = 5000,
    leverage: int = 1,
    position_idx: int = 0,
    limiter: Optional[AdaptiveRateLimiter] = None,
    metrics=None,
    service_name: str = "unknown",
) -> BybitV5LinearClient:
    if limiter is None:
        limiter = AdaptiveRateLimiter()
    return BybitV5LinearClient(
        base_url=base_url,
        api_key=api_key,
        api_secret=api_secret,
        recv_window=recv_window,
        leverage=leverage,
        position_idx=position_idx,
        limiter=limiter,
        metrics=metrics,
        service_name=service_name,
    )
