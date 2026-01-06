# data/syncer.py
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from database.db_manager import db
from core.exchange_gateway import gateway
from data.indicators import IndicatorEngine
from config.settings import settings, UTC_TZ, HK_TZ
from config.logging_config import setup_logger

logger = setup_logger("data_syncer")


class DataSyncer:
    def __init__(self):
        self.engine = db.get_engine()
        self.symbols = ["BTC/USDT", "ETH/USDT"]  # 可从 system_config 读取
        self.timeframe = "15m"
        self.lookback_buffer = 100  # 计算指标需要的历史长度

    def get_last_synced_ts(self, symbol):
        """查询数据库中最新的 K 线时间 (UTC)"""
        query = text("""
                     SELECT MAX(kline_open_ts_utc)
                     FROM market_data
                     WHERE symbol = :symbol
                       AND timeframe = :tf
                     """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {"symbol": symbol, "tf": self.timeframe}).scalar()
        return result if result else 0

    def load_historical_buffer(self, symbol):
        """加载最近 N 条记录用于指标计算初始化"""
        query = text("""
                     SELECT kline_open_ts_utc as timestamp, open_price as open, 
                   high_price as high, low_price as low, 
                   close_price as close, volume
                     FROM market_data
                     WHERE symbol = :symbol AND timeframe = :tf
                     ORDER BY kline_open_ts_utc DESC LIMIT :limit
                     """)
        with self.engine.connect() as conn:
            # 读出来是倒序，需要反转为正序
            df = pd.read_sql(query, conn,
                             params={"symbol": symbol, "tf": self.timeframe, "limit": self.lookback_buffer})

        if not df.empty:
            df = df.sort_values(by="timestamp").reset_index(drop=True)
        return df

    def save_batch(self, symbol, df_new_calculated):
        """
        事务写入：Raw Data -> market_data, Indicators -> market_data_cache
        V8.3 3.3 唯一键约束防止重复
        """
        if df_new_calculated.empty:
            return

        raw_data = []
        cache_data = []

        now_utc = datetime.now(UTC_TZ)

        for _, row in df_new_calculated.iterrows():
            ts_utc = int(row['timestamp'])

            # 1. 准备 Raw Data
            raw_data.append({
                "symbol": symbol,
                "timeframe": self.timeframe,
                "kline_open_ts_utc": ts_utc,
                "open_price": row['open'],
                "high_price": row['high'],
                "low_price": row['low'],
                "close_price": row['close'],
                "volume": row['volume']
            })

            # 2. 准备 Indicators JSON
            indicators = {
                "adx": round(row['adx'], 2),
                "di_plus": round(row['plus_di'], 2),
                "di_minus": round(row['minus_di'], 2),
                "ema_21": round(row['ema_21'], 2),
                "ema_50": round(row['ema_50'], 2),
                "squeeze_on": bool(row['squeeze_on']),
                "momentum": round(row['momentum_val'], 4),
                "vol_ratio": round(row['vol_ratio'], 2)
            }

            cache_data.append({
                "symbol": symbol,
                "timeframe": self.timeframe,
                "kline_open_ts_utc": ts_utc,
                "feature_version": "v1",
                "indicators_json": json.dumps(indicators)
            })

        # 执行写入 (使用 IGNORE 忽略重复)
        # 注意: SQLAlchemy Core 批量插入通常较快
        with self.engine.begin() as conn:
            # Insert Market Data
            stmt_raw = text("""
                            INSERT
                            IGNORE INTO market_data 
                (symbol, timeframe, kline_open_ts_utc, open_price, high_price, low_price, close_price, volume)
                VALUES (:symbol, :timeframe, :kline_open_ts_utc, :open_price, :high_price, :low_price, :close_price, :volume)
                            """)
            conn.execute(stmt_raw, raw_data)

            # Insert Cache
            stmt_cache = text("""
                              INSERT
                              IGNORE INTO market_data_cache
                (symbol, timeframe, kline_open_ts_utc, feature_version, indicators_json)
                VALUES (:symbol, :timeframe, :kline_open_ts_utc, :feature_version, :indicators_json)
                              """)
            conn.execute(stmt_cache, cache_data)

        logger.info(f"Saved {len(raw_data)} candles for {symbol}",
                    extra={"action": "DATA_SYNC", "reason_code": "SAVE_BATCH",
                           "reason": f"Range {raw_data[0]['kline_open_ts_utc']} - {raw_data[-1]['kline_open_ts_utc']}"})

    def sync_symbol(self, symbol):
        # 1. 获取 DB 中最后的时间戳
        last_ts = self.get_last_synced_ts(symbol)

        # 2. 获取历史 Buffer (用于指标计算)
        df_buffer = self.load_historical_buffer(symbol)

        # 3. 从交易所拉取数据 (CCXT)
        # 如果是首次运行 (last_ts=0)，拉取最近 1000 根
        # 否则，拉取 last_ts 之后的数据
        since = last_ts + 1 if last_ts > 0 else None
        limit = 1000 if last_ts == 0 else 100

        # 使用 Gateway 拉取
        # 注意: fetch_ohlcv 需要根据 API 不同处理 since。
        # 这里简化处理：直接 fetch 最新，然后自己在内存里过滤
        ohlcv_list = gateway.exchange_client.fetch_ohlcv(symbol, self.timeframe, limit=limit)

        if not ohlcv_list:
            return

        # 转换为 DataFrame
        df_new = pd.DataFrame(ohlcv_list, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # 过滤掉已经存在的数据 ( timestamp <= last_ts )
        # 同时过滤掉未收盘的 K 线 (如果 timestamp + 15m > now) -> 策略层通常只用已收盘
        # 这里假设 fetch_ohlcv 返回的都是已完成或包含最新。
        # V8.3 要求：只落库已固化的数据? 通常为了实时性，最新一根如果是未完成的，不应入库(或者入库标记未完成)。
        # 简单策略：仅入库 timestamp < 当前时间 - 15m 的 (即已收盘)
        # *修正*: CCXT 返回的时间戳是开盘时间。
        # 假设当前 12:05, 12:00 的 K 线还在走，不能存。11:45 的 K 线已走完，可以存。
        current_time = time.time() * 1000
        fifteen_min_ms = 15 * 60 * 1000

        # 过滤掉：已经存在 OR 尚未走完
        df_new = df_new[
            (df_new['timestamp'] > last_ts) &
            (df_new['timestamp'] + fifteen_min_ms < current_time)
            ]

        if df_new.empty:
            return

        # 4. 合并 Buffer 和 New Data 进行计算
        df_total = pd.concat([df_buffer, df_new]).drop_duplicates(subset=['timestamp']).sort_values(by='timestamp')

        # 5. 计算指标
        df_calculated = IndicatorEngine.calculate_all(df_total)

        # 6. 截取“新”的部分进行保存
        # 只要 timestamp 在 df_new 里的
        new_timestamps = set(df_new['timestamp'])
        df_to_save = df_calculated[df_calculated['timestamp'].isin(new_timestamps)]

        # 7. 落库
        self.save_batch(symbol, df_to_save)

        # 8. 上报状态 (Heartbeat / Lag)
        self.report_status(symbol, df_to_save['timestamp'].max())

    def report_status(self, symbol, last_kline_ts):
        """写入 service_status 表"""
        lag_seconds = (time.time() * 1000 - last_kline_ts) / 1000
        meta = json.dumps({"lag_seconds": lag_seconds, "last_symbol": symbol})

        stmt = text("""
                    INSERT INTO service_status (service_name, status, last_heartbeat_hk, metadata_json)
                    VALUES ('data-syncer', 'RUNNING', :now_hk, :meta) ON DUPLICATE KEY
                    UPDATE
                        status='RUNNING', last_heartbeat_hk=:now_hk, metadata_json=:meta
                    """)
        with self.engine.connect() as conn:
            conn.execute(stmt, {"now_hk": datetime.now(HK_TZ), "meta": meta})
            conn.commit()

    def run(self):
        logger.info("Data Syncer Started", extra={"action": "STARTUP", "reason_code": "INIT", "reason": "Service boot"})
        while True:
            try:
                for symbol in self.symbols:
                    self.sync_symbol(symbol)
                    time.sleep(1)  # Symbol 间间隔，防瞬时风暴

                # 轮询间隔：15秒
                time.sleep(15)

            except Exception as e:
                logger.error(f"Sync Loop Error: {e}",
                             extra={"action": "CRASH", "reason_code": "LOOP_ERR", "reason": str(e)})
                time.sleep(30)  # 出错多睡会


if __name__ == "__main__":
    syncer = DataSyncer()
    syncer.run()