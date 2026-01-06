from __future__ import annotations

import datetime
import json
import os
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

        # ✅ 新增：是否发送 JSON 摘要（默认开启）
        self.send_json = self._get_bool_env("TELEGRAM_SEND_JSON", default=True)

    @staticmethod
    def _get_bool_env(name: str, default: bool = True) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):
            return True
        if s in ("0", "false", "no", "n", "off"):
            return False
        return default

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _post_form(self, url: str, data: Dict[str, Any]) -> bool:
        try:
            body = urlencode({k: "" if v is None else str(v) for k, v in data.items()}).encode("utf-8")
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                _ = resp.read()
            return True
        except Exception:
            return False

    def _send_message(self, text: str, parse_mode: Optional[str] = None) -> None:
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
            # ✅ 文本默认不使用 Markdown，避免 '_' 导致解析失败
            if parse_mode:
                payload["parse_mode"] = parse_mode
            self._post_form(url, payload)

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

    def send_alert(self, title: str, summary_lines: List[str], payload: Dict[str, Any], json_indent: int = 2) -> None:
        if not self.enabled():
            return

        summary_lines = summary_lines or []
        text_msg = "\n".join([title, *summary_lines]).strip()

        # 1) ✅ 文本：永远发送
        self._send_message(text_msg, parse_mode=None)

        # 2) ✅ JSON：可通过环境变量关闭
        if not self.send_json:
            return

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

        payload_json_html = html_escape(payload_json)
        html_msg = f"<b>JSON 摘要</b>\n<pre>{payload_json_html}</pre>"
        self._send_message(html_msg, parse_mode="HTML")

    def send_alert_zh(self, title: str, summary_kv: Dict[str, Any], payload: Dict[str, Any]) -> None:
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
