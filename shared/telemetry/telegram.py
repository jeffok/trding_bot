from __future__ import annotations

import html
import json
from typing import Any, Dict, Iterable

import httpx


class Telegram:
    """Telegram 告警发送器。

    设计目标：
    - 发送内容：中文文本 + JSON 摘要（便于机器解析 / 后续落库）
    - 只影响“发到 Telegram 看到的文本”，不要求内部字段/数据库也改中文
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    # 兼容旧接口
    def send(self, text: str) -> None:
        self.send_text(text)

    def send_text(self, text: str) -> None:
        if not self.enabled():
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as client:
                client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                )
        except Exception:
            # 告警失败不能影响交易主循环
            pass

    def send_html(self, html_text: str) -> None:
        if not self.enabled():
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as client:
                client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": html_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
        except Exception:
            pass

    def send_alert(
        self,
        *,
        title: str,
        summary_lines: Iterable[str],
        payload: Dict[str, Any],
        json_indent: int = 2,
        max_len: int = 3900,
    ) -> None:
        """发送：标题 + 摘要 + JSON（HTML 格式）"""
        if not self.enabled():
            return

        summary = "\n".join([str(x) for x in summary_lines if str(x).strip()])
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=json_indent)

        title_e = html.escape(str(title))
        summary_e = html.escape(summary)
        payload_e = html.escape(payload_json)

        head = f"<b>{title_e}</b>\n{summary_e}\n\n<pre><code>"
        tail = "</code></pre>"
        msg = head + payload_e + tail

        if len(msg) > max_len:
            allowed = max(0, max_len - len(head) - len(tail) - 40)
            payload_trunc = payload_e[:allowed] + "\n...（内容过长已截断）"
            msg = head + payload_trunc + tail

        self.send_html(msg)

    # -------------------------
    # 展示中文化（仅 Telegram 文本层）
    # -------------------------
    _KEY_ZH: Dict[str, str] = {
        "level": "级别",
        "event": "事件",
        "service": "服务",
        "trace_id": "追踪ID",
        "exchange": "交易所",
        "symbol": "交易对",
        "side": "方向",
        "qty": "数量",
        "price": "价格",
        "entry_price": "开仓价",
        "avg_entry_price": "均价",
        "stop_price": "止损价",
        "client_order_id": "客户端订单ID",
        "exchange_order_id": "交易所订单ID",
        "reason_code": "原因码",
        "reason": "原因说明",
        "pnl_usdt": "盈亏(USDT)",
        "fee_usdt": "手续费(USDT)",
        "note": "说明",
        "error": "错误详情",
    }

    _EVENT_ZH: Dict[str, str] = {
        "BUY_FILLED": "开仓成交",
        "SELL_FILLED": "平仓成交",
        "STOP_LOSS": "触发止损",
        "EMERGENCY_EXIT_EXECUTED": "紧急退出已执行",
    }

    _SIDE_ZH: Dict[str, str] = {"BUY": "买入", "SELL": "卖出"}

    _REASON_ZH: Dict[str, str] = {
        "STRATEGY_SIGNAL": "策略信号",
        "STOP_LOSS": "止损",
        "EMERGENCY_EXIT": "紧急退出",
        "ADMIN_HALT": "管理暂停",
        "DATA_SYNC": "行情同步",
        "SYSTEM": "系统异常",
    }

    def _k(self, key: str) -> str:
        return self._KEY_ZH.get(key, key)

    def _v(self, key: str, val: Any) -> Any:
        if val is None:
            return val
        if key == "event":
            return self._EVENT_ZH.get(str(val), val)
        if key == "side":
            return self._SIDE_ZH.get(str(val).upper(), val)
        if key == "reason_code":
            return self._REASON_ZH.get(str(val), val)
        # 交易对/交易所：按你的要求保持原样，不翻译
        return val

    def _translate(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                ks = str(k)
                out[self._k(ks)] = self._v(ks, self._translate(v))
            return out
        if isinstance(obj, list):
            return [self._translate(x) for x in obj]
        return obj

    def send_alert_zh(self, *, title: str, summary_kv: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """中文文本 + JSON 摘要（JSON key/value 做中文化展示）。"""
        s = self._translate(summary_kv)
        p = self._translate(payload)

        summary_lines = [f"{k}={v}" for k, v in s.items()]
        self.send_alert(title=title, summary_lines=summary_lines, payload=p, json_indent=2)
