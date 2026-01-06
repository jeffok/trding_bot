from __future__ import annotations

"""
Telegram 告警发送模块（不依赖第三方库）

修复点：
- 文本消息不再使用 Markdown（避免 trace_id/字段名里的 '_' 导致 Telegram 解析失败）
- JSON 摘要用 HTML 的 <pre> 发送（显示整齐且不需要复杂转义）
- 仍然支持 datetime / Decimal 的 JSON 序列化兜底
- 自动分片发送（单条消息长度限制）

注意：
- 如果未配置 bot_token 或 chat_id，enabled() 返回 False，发送函数会静默返回
"""

import datetime
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from html import escape as html_escape


class Telegram:
    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: int = 10) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self.timeout_seconds = int(timeout_seconds)

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    # -----------------------------
    # HTTP POST（urllib）
    # -----------------------------
    def _post_form(self, url: str, data: Dict[str, Any]) -> bool:
        """以 form-urlencoded POST。失败返回 False，不抛异常（告警不影响主流程）。"""
        try:
            body = urlencode({k: "" if v is None else str(v) for k, v in data.items()}).encode("utf-8")
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                # Telegram 成功一般是 200，失败也可能返回 200 但 ok=false，这里不做强依赖解析
                _ = resp.read()
            return True
        except Exception:
            return False

    def _send_message(self, text: str, parse_mode: Optional[str] = None) -> None:
        """
        发送消息（自动分片）。
        Telegram 单条消息限制约 4096，这里用更保守的 3500。
        """
        if not self.enabled():
            return

        s = text or ""
        max_len = 3500
        parts: List[str] = []
        while len(s) > max_len:
            parts.append(s[:max_len])
            s = s[max_len:]
        if s:
            parts.append(s)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        for part in parts:
            payload: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": part,
                "disable_web_page_preview": "true",
            }
            # ✅ 默认不使用 Markdown，避免 '_' 导致解析失败
            if parse_mode:
                payload["parse_mode"] = parse_mode

            self._post_form(url, payload)

    # -----------------------------
    # JSON 序列化兜底
    # -----------------------------
    @staticmethod
    def _json_default(o: Any) -> Any:
        if isinstance(o, (datetime.datetime, datetime.date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            try:
                return float(o)
            except Exception:
                return str(o)
        return str(o)

    # -----------------------------
    # 对外：告警发送
    # -----------------------------
    def send_alert(self, title: str, summary_lines: List[str], payload: Dict[str, Any], json_indent: int = 2) -> None:
        """
        发送告警：先发“纯文本”，再发“HTML 预格式化 JSON”
        """
        if not self.enabled():
            return

        summary_lines = summary_lines or []
        text_msg = "\n".join([title, *summary_lines]).strip()

        # 1) ✅ 文本：纯文本发送（不带 parse_mode，避免 Markdown 解析错误）
        self._send_message(text_msg, parse_mode=None)

        # 2) JSON：HTML <pre> 发送（更稳定、更好看）
        try:
            payload_json = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=json_indent,
                default=self._json_default,
            )
        except Exception as e:
            payload_json = json.dumps(
                {"_error": f"payload json encode failed: {str(e)}", "payload_str": str(payload)},
                ensure_ascii=False,
                sort_keys=True,
                indent=json_indent,
                default=self._json_default,
            )

        # HTML 需要转义 < > &
        payload_json_html = html_escape(payload_json)
        html_msg = f"<b>JSON 摘要</b>\n<pre>{payload_json_html}</pre>"

        self._send_message(html_msg, parse_mode="HTML")

    def send_alert_zh(self, title: str, summary_kv: Dict[str, Any], payload: Dict[str, Any]) -> None:
        """
        中文告警：summary_kv 用列表展示 + JSON 摘要
        """
        if not self.enabled():
            return

        lines: List[str] = []
        for k, v in (summary_kv or {}).items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                v2 = v.isoformat()
            else:
                v2 = v
            lines.append(f"- {k}: {v2}")

        self.send_alert(title=title, summary_lines=lines, payload=payload, json_indent=2)
