# test_exchange.py
import time
from core.exchange_gateway import gateway
from core.rate_limiter import rate_limiter


def test_rate_limit():
    print("Testing Rate Limiter...")

    # 模拟快速请求
    for i in range(5):
        print(f"Request {i + 1}")
        # 这里实际上会调用 fetch_ohlcv -> acquire -> check limit
        # 如果你没有配置真实 API Key，这里会报错 AuthenticationError，
        # 但我们可以观察日志中是否有 "Local limit reached" (如果把 limit 改得很小)
        try:
            gateway.get_latest_kline("BTC/USDT", "15m")
        except Exception as e:
            print(f"Expected API error (no keys): {e}")

    print("Test finished.")


if __name__ == "__main__":
    test_rate_limit()