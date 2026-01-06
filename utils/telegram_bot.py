# utils/telegram_bot.py
import requests
from config.settings import settings
from config.logging_config import setup_logger

logger = setup_logger("telegram")


class TelegramBot:
    def __init__(self):
        self.token = settings.TG_BOT_TOKEN
        self.chat_id = settings.TG_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_alert(self, title: str, message: str, level: str = "INFO", fields: dict = None):
        """
        发送结构化告警
        fields 必须包含: reason_code, reason, action 等
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram token/chat_id not set, skipping alert.")
            return

        # 图标映射
        icons = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "🚨",
            "SUCCESS": "✅",
            "TRADE": "💰",
            "STOP": "🛑"
        }
        icon = icons.get(level, "📢")

        # 构造消息体
        text = f"{icon} *{title}*\n\n"
        text += f"{message}\n\n"

        if fields:
            text += "──────────────\n"
            for k, v in fields.items():
                text += f"*{k}*: `{v}`\n"

        # 发送
        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            resp = requests.post(self.base_url, json=payload, timeout=5)
            if resp.status_code != 200:
                logger.error(f"TG Send Failed: {resp.text}",
                             extra={"action": "ALERT", "reason_code": "TG_ERR", "reason": "API Error"})
        except Exception as e:
            logger.error(f"TG Network Error: {str(e)}",
                         extra={"action": "ALERT", "reason_code": "TG_ERR", "reason": str(e)})


tg_bot = TelegramBot()