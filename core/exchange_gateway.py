# core/exchange_gateway.py
from core.exchange_client import exchange_client
from config.logging_config import setup_logger

logger = setup_logger("exchange_gateway")


class ExchangeGateway:
    """
    业务逻辑层：
    - 格式化数据
    - 确保必要的参数存在 (如 client_order_id)
    """

    def get_latest_kline(self, symbol: str, timeframe: str):
        """获取单根最新 K 线，用于实时判定"""
        try:
            # limit=2 确保能拿到倒数第二根（已收盘）和倒数第一根（进行中）
            ohlcv = exchange_client.fetch_ohlcv(symbol, timeframe, limit=5)
            # 格式转换: [ts, o, h, l, c, v]
            return ohlcv
        except Exception as e:
            logger.error(f"Get KLine failed: {symbol}",
                         extra={"action": "GET_DATA", "reason_code": "FETCH_FAIL", "reason": str(e)})
            return []

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float,
                    price: float = None, client_order_id: str = None, reduce_only: bool = False):
        """
        核心下单接口
        """
        if not client_order_id:
            raise ValueError("client_order_id is mandatory for idempotency (V8.3 2.1)")

        params = {'newClientOrderId': client_order_id}
        if reduce_only:
            params['reduceOnly'] = True

        try:
            # 调用底层
            response = exchange_client.create_order(
                symbol=symbol,
                type=order_type.lower(),
                side=side.lower(),
                amount=quantity,
                price=price,
                params=params
            )
            return response
        except Exception as e:
            # 这里不再 try-catch，异常应抛出给 Strategy Engine 处理以便写 ERROR 事件
            raise e

    def set_isolated_margin(self, symbol: str, leverage: int):
        """
        V8.3 8.1: 设置逐仓和杠杆
        """
        try:
            # 设置杠杆
            exchange_client.set_leverage(symbol, leverage)
            # 注意：设置逐仓模式通常只需一次，且不同交易所 API 差异大。
            # 此处简化，实盘需根据 Exchange API 文档补全 set_margin_mode
            logger.info(f"Leverage set to {leverage}x for {symbol}",
                        extra={"action": "CONFIG_ACC", "reason_code": "RISK_CTRL", "reason": "Init leverage"})
        except Exception as e:
            logger.error(f"Set leverage failed: {e}",
                         extra={"action": "CONFIG_ACC", "reason_code": "API_ERR", "reason": str(e)})


gateway = ExchangeGateway()