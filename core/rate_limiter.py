# core/rate_limiter.py
import time
import threading
import random
from config.logging_config import setup_logger

logger = setup_logger("rate_limiter")


class AdaptiveRateLimiter:
    """
    V8.3 智能节流实现：
    1. 解析交易所响应头 (used-weight)
    2. 遇到 429/418 自动退避 (Exponential Backoff)
    3. 分组限流 (Market/Order/Account)
    """

    def __init__(self):
        self.lock = threading.Lock()

        # 默认限制 (保守值，初始化后会根据响应动态调整)
        self.limits = {
            "default": {"max": 1200, "used": 0, "window": 60, "reset_ts": time.time() + 60},
            "orders": {"max": 50, "used": 0, "window": 10, "reset_ts": time.time() + 10}
        }

        # 429 退避状态
        self.backoff_until = 0
        self.backoff_stage = 0  # 连续 429 次数

    def _check_backoff(self):
        """检查是否处于惩罚期"""
        now = time.time()
        if now < self.backoff_until:
            wait_time = self.backoff_until - now
            logger.warning(f"Global backoff active. Waiting {wait_time:.2f}s",
                           extra={"action": "RATE_LIMIT_WAIT", "reason_code": "COOL_DOWN", "reason": "In penalty box"})
            time.sleep(wait_time)

    def acquire(self, weight=1, group="default"):
        """
        请求前调用，检查预算
        """
        with self.lock:
            self._check_backoff()

            # 简单窗口重置逻辑
            now = time.time()
            limit_info = self.limits.get(group, self.limits["default"])

            if now > limit_info["reset_ts"]:
                # 窗口过期，重置 used (实际逻辑会更复杂，这里简化为重置)
                limit_info["used"] = 0
                limit_info["reset_ts"] = now + limit_info["window"]

            # 预检查：如果本地计算已超标，主动 sleep
            if limit_info["used"] + weight > limit_info["max"] * 0.95:  # 留 5% 缓冲
                sleep_time = max(0.5, limit_info["reset_ts"] - now)
                logger.info(f"Local limit reached for {group}. Sleeping {sleep_time:.2f}s",
                            extra={"action": "RATE_LIMIT_LOCAL", "reason_code": "BUDGET_EXHAUSTED",
                                   "reason": f"Used {limit_info['used']}/{limit_info['max']}"})
                time.sleep(sleep_time)
                # 醒来后继续，假设窗口已重置
                limit_info["used"] = 0
                limit_info["reset_ts"] = time.time() + limit_info["window"]

            limit_info["used"] += weight

    def update_from_headers(self, headers: dict):
        """
        V8.3 5.3: 解析响应头动态调参
        Binance 示例: x-mbx-used-weight-1m
        """
        if not headers:
            return

        with self.lock:
            # 示例：解析 Binance 1分钟权重
            used_weight = headers.get('x-mbx-used-weight-1m')
            if used_weight:
                try:
                    val = int(used_weight)
                    self.limits["default"]["used"] = val
                    # 动态日志：当使用率超过 80% 时警告
                    if val > self.limits["default"]["max"] * 0.8:
                        logger.warning(f"High API weight usage: {val}",
                                       extra={"action": "RATE_LIMIT_WARN", "reason_code": "HIGH_LOAD",
                                              "reason": "Exchange header reported high usage"})
                except ValueError:
                    pass

    def handle_429(self, retry_after=None):
        """
        V8.3 5.3: 触发退避机制
        """
        with self.lock:
            self.backoff_stage += 1

            # 如果 Header 有 Retry-After，优先使用
            if retry_after:
                wait_s = int(retry_after)
            else:
                # 指数退避 + 抖动: 2^stage + random
                wait_s = (2 ** self.backoff_stage) + random.uniform(0.1, 1.0)

            # 封顶 60秒
            wait_s = min(wait_s, 60)

            self.backoff_until = time.time() + wait_s

            logger.error(f"429 Triggered! Backoff level {self.backoff_stage}, wait {wait_s:.2f}s",
                         extra={"action": "RATE_LIMIT_BACKOFF", "reason_code": "RATE_LIMIT_429",
                                "reason": "Exchange rejected request"})

    def reset_backoff(self):
        """成功请求后缓慢重置退避等级"""
        if self.backoff_stage > 0:
            self.backoff_stage = max(0, self.backoff_stage - 1)


# 全局单例
rate_limiter = AdaptiveRateLimiter()