# strategy/engine.py
import time
import json
import uuid
from datetime import datetime
from sqlalchemy import text
from database.db_manager import db
from core.exchange_gateway import gateway
from utils.telegram_bot import tg_bot
from config.settings import settings, HK_TZ
from config.logging_config import setup_logger
from strategy.signals import SignalDetector
from strategy.risk import RiskManager

logger = setup_logger("strategy_engine")


class StrategyEngine:
    def __init__(self):
        self.engine = db.get_engine()
        self.symbols = ["BTC/USDT", "ETH/USDT"]
        self.timeframe = "15m"
        self.risk_manager = RiskManager()
        self.ai_score_default = 50  # V8.3 7.1 冷启动

    def _get_indicators(self, symbol):
        """从缓存表读取最近两根指标 (V8.3 4.1.1 步骤 3)"""
        query = text("""
                     SELECT indicators_json
                     FROM market_data_cache
                     WHERE symbol = :symbol
                       AND timeframe = :tf
                     ORDER BY kline_open_ts_utc DESC LIMIT 2
                     """)
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"symbol": symbol, "tf": self.timeframe}).fetchall()

        if len(rows) < 2:
            return None, None

        # rows[0] 是最新的 (Current), rows[1] 是前一根 (Prev)
        return json.loads(rows[0][0]), json.loads(rows[1][0])

    def _generate_client_order_id(self, symbol, side):
        """V8.3 4.1.2 幂等键生成"""
        # 格式: asv8-{symbol}-{side}-{timeframe}-{ts}-{nonce}
        ts = int(time.time() * 1000)
        nonce = str(uuid.uuid4())[:8]
        return f"asv8-{symbol.replace('/', '')}-{side}-{self.timeframe}-{ts}-{nonce}"

    def _audit_event(self, client_order_id, event_type, symbol, side, **kwargs):
        """V8.3 2.1 事件落库"""
        stmt = text("""
                    INSERT INTO order_events
                    (client_order_id, event_type, symbol, side, order_type, reason_code, reason, event_ts_utc,
                     raw_payload_json)
                    VALUES (:cid, :etype, :sym, :side, 'MARKET', :rcode, :reason, :ts, :payload)
                    """)
        payload = json.dumps(kwargs.get('payload', {}))

        with self.engine.begin() as conn:
            conn.execute(stmt, {
                "cid": client_order_id,
                "etype": event_type,
                "sym": symbol,
                "side": side,
                "rcode": kwargs.get('reason_code', 'UNKNOWN'),
                "reason": kwargs.get('reason', 'No reason provided'),
                "ts": int(time.time() * 1000),
                "payload": payload
            })

    def process_symbol(self, symbol):
        # 1. 读数据
        curr_ind, prev_ind = self._get_indicators(symbol)
        if not curr_ind:
            logger.warning(f"No indicators for {symbol}",
                           extra={"action": "SKIP", "reason_code": "NO_DATA", "reason": "Cache empty"})
            return

        # 2. 信号检测 (Setup B)
        # 假设当前只做多 (Long)
        is_signal, sig_code, sig_reason = SignalDetector.check_setup_b_long(curr_ind, prev_ind)

        if not is_signal:
            return  # 无信号，静默跳过

        logger.info(f"Signal Found: {symbol}",
                    extra={"action": "SIGNAL", "reason_code": sig_code, "reason": sig_reason})

        # 3. 获取最新价格 (用于风控计算)
        try:
            kline = gateway.get_latest_kline(symbol, self.timeframe)
            current_price = kline[-1][4]  # Close of latest

            # 止损策略 (V8.3 6.4): ATR 止损或低点止损
            # 这里简化: 使用 ATR * 2 止损
            atr = curr_ind.get('atr_20', current_price * 0.02)  # 兜底 2%
            stop_loss_price = current_price - (atr * 2.0)

            # 余额查询
            balance_data = gateway.exchange_client.fetch_balance()
            equity = float(balance_data['total']['USDT'])

        except Exception as e:
            logger.error(f"Pre-trade check failed: {e}",
                         extra={"action": "ABORT", "reason_code": "DATA_ERR", "reason": str(e)})
            return

        # 4. 风控计算
        is_safe, qty, leverage, risk_reason = self.risk_manager.calculate_position_size(
            equity, self.ai_score_default, current_price, stop_loss_price
        )

        if not is_safe:
            logger.warning(f"Risk Rejected: {symbol}",
                           extra={"action": "RISK_BLOCK", "reason_code": "RISK_LIMIT", "reason": risk_reason})
            # 可选: 发送 Telegram 告知错过机会
            return

        # 5. 执行阶段 (State Machine)
        side = "buy"
        cid = self._generate_client_order_id(symbol, side)

        # Step 5.1: CREATED Event
        self._audit_event(cid, "CREATED", symbol, side,
                          reason_code=sig_code,
                          reason=f"{sig_reason} | {risk_reason}")

        # Step 5.2: Configure Margin/Leverage
        gateway.set_isolated_margin(symbol, leverage)

        # Step 5.3: Submit Order
        try:
            # 发送告警
            tg_bot.send_alert("🚀 开仓信号触发",
                              f"Symbol: {symbol}\nPrice: {current_price}\nStop: {stop_loss_price}\nSize: {qty}\nLev: {leverage}x",
                              fields={"reason": sig_reason, "risk": risk_reason})

            order_resp = gateway.place_order(symbol, side, "MARKET", qty, client_order_id=cid)

            # Step 5.4: SUBMITTED / FILLED Event
            # 交易所通常立即返回 Pending 或 Filled
            status = order_resp.get('status', 'unknown').upper()
            self._audit_event(cid, status, symbol, side,
                              reason_code="API_OK",
                              reason=f"Order placed. ID: {order_resp['id']}",
                              payload=order_resp)

            # Step 5.5: 设置止损单 (必须)
            # 很多交易所支持 OCO 或单独 StopOrder。这里演示单独下 Stop Market。
            sl_cid = f"{cid}-sl"
            gateway.place_order(symbol, "sell", "STOP_MARKET", qty,
                                price=None,  # Stop Market 不需要限价
                                client_order_id=sl_cid,
                                reduce_only=True,
                                # CCXT params needed for trigger price
                                params={'stopPrice': stop_loss_price}
                                )
            tg_bot.send_alert("🛡️ 止损已设置", f"Price: {stop_loss_price}", level="INFO")

        except Exception as e:
            # Step 5.6: ERROR Event
            self._audit_event(cid, "ERROR", symbol, side,
                              reason_code="EXEC_FAIL",
                              reason=str(e))
            tg_bot.send_alert("🚨 下单失败", str(e), level="ERROR", fields={"cid": cid})

    def run(self):
        logger.info("Strategy Engine Started",
                    extra={"action": "STARTUP", "reason_code": "INIT", "reason": "Engine boot"})
        while True:
            # 1. 简单的定时触发 (生产环境应用 Schedule 或准确对齐时间)
            # 这里简化: 每 10 秒轮询一次，检查是否是 15分 的整点附近 (0-10s)
            now = datetime.now(HK_TZ)

            # 仅在每 15 分钟的前 15 秒内执行一次
            if now.minute % 15 == 0 and now.second < 15:
                logger.info("Tick Triggered",
                            extra={"action": "TICK", "reason_code": "TIME_MATCH", "reason": now.strftime("%H:%M:%S")})

                for symbol in self.symbols:
                    self.process_symbol(symbol)

                # 防止单次 Tick 重复执行，休眠到下一分钟
                time.sleep(60)

            else:
                time.sleep(1)


if __name__ == "__main__":
    engine = StrategyEngine()
    engine.run()