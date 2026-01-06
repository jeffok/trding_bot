# config/logging_config.py
import logging
import json
import sys
from datetime import datetime
from config.settings import settings, HK_TZ


class JSONFormatter(logging.Formatter):
    """
    符合 V8.3 审计要求的 JSON 日志格式器
    """

    def format(self, record):
        # 获取当前 HK 时间
        now_hk = datetime.now(HK_TZ).isoformat()

        log_record = {
            "ts": now_hk,
            "level": record.levelname,
            "service": "alpha-sniper",  # 可以在各服务中覆盖
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
        }

        # 提取结构化字段 (V8.3 2.3 节要求)
        if hasattr(record, "action"):
            log_record["action"] = record.action
        if hasattr(record, "reason_code"):
            log_record["reason_code"] = record.reason_code
        if hasattr(record, "reason"):
            log_record["reason"] = record.reason
        if hasattr(record, "trace_id"):
            log_record["trace_id"] = record.trace_id
        if hasattr(record, "client_order_id"):
            log_record["client_order_id"] = record.client_order_id

        return json.dumps(log_record, ensure_ascii=False)


def setup_logger(name="alpha_sniper"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger

# 使用示例:
# logger.info("Order Submitted", extra={"action": "SUBMIT_ORDER", "reason_code": "SETUP_B", "reason": "Squeeze release"})