# core/exchange_client.py
import ccxt
import json
import time
from config.settings import settings
from config.logging_config import setup_logger
from core.rate_limiter import rate_limiter

logger = setup_logger("exchange_client")


class ExchangeClient:
    def __init__(self):
        exchange_class = getattr(ccxt, settings.EXCHANGE_ID)
        self.api = exchange_class({
            'apiKey': settings.API_KEY,
            'secret': settings.API_SECRET,
            'enableRateLimit': False,  # 禁用 CCXT 自带，使用我们自己的 V8.3 智能节流
            'options': {
                'defaultType': 'future',  # 默认合约
                'adjustForTimeDifference': True
            }
        })
        # 加载市场结构（耗费权重，需注意）
        self._load_markets()

    def _load_markets(self):
        try:
            self.api.load_markets()
        except Exception as e:
            logger.error(f"Failed to load markets: {e}",
                         extra={"action": "INIT", "reason_code": "NET_ERR", "reason": str(e)})

    def _execute(self, method_name, *args, **kwargs):
        """
        通用执行包装器：限流 -> 执行 -> 解析Header -> 异常处理
        """
        weight = kwargs.pop('cost', 1)  # 预估权重

        # 1. 限流申请
        rate_limiter.acquire(weight=weight)

        try:
            method = getattr(self.api, method_name)

            # 2. 实际调用
            response = method(*args, **kwargs)

            # 3. 更新限流状态 (CCXT last_response_headers)
            if self.api.last_response_headers:
                rate_limiter.update_from_headers(self.api.last_response_headers)

            # 成功则重置退避等级
            rate_limiter.reset_backoff()

            return response

        except ccxt.RateLimitExceeded as e:
            # 4. 捕获 429
            # 尝试提取 Retry-After (CCXT 可能会解析在 e 里面，这里简化处理)
            rate_limiter.handle_429()
            logger.error(f"RateLimitExceeded: {e}",
                         extra={"action": "API_ERROR", "reason_code": "HTTP_429", "reason": str(e)})
            raise e

        except ccxt.ExchangeError as e:
            # 5. 常规错误
            logger.error(f"ExchangeError: {e}",
                         extra={"action": "API_ERROR", "reason_code": "EXCHANGE_ERR", "reason": str(e)})
            raise e
        except Exception as e:
            logger.error(f"Unknown Error: {e}",
                         extra={"action": "API_ERROR", "reason_code": "UNKNOWN_ERR", "reason": str(e)})
            raise e

    # --- 暴露给 Gateway 的原始方法 ---

    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        # 权重假设：K线通常较重
        return self._execute('fetch_ohlcv', symbol, timeframe, limit=limit, cost=2)

    def create_order(self, symbol, type, side, amount, price=None, params={}):
        return self._execute('create_order', symbol, type, side, amount, price, params, cost=1)

    def cancel_order(self, id, symbol):
        return self._execute('cancel_order', id, symbol, cost=1)

    def fetch_order(self, id, symbol):
        return self._execute('fetch_order', id, symbol, cost=1)

    def fetch_balance(self):
        return self._execute('fetch_balance', params={'type': 'future'}, cost=5)

    def set_leverage(self, symbol, leverage):
        return self._execute('set_leverage', leverage, symbol, cost=1)


exchange_client = ExchangeClient()