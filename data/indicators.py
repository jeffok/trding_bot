# data/indicators.py
import pandas as pd
import numpy as np


class IndicatorEngine:
    """
    负责将原始 OHLCV 数据转换为策略可用的指标集。
    输入: Pandas DataFrame (columns: timestamp, open, high, low, close, volume)
    输出: 包含指标的 DataFrame
    """

    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.copy()

        # 1. 基础 EMA (V8.3: EMA21, EMA50/55)
        df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_55'] = df['close'].ewm(span=55, adjust=False).mean()  # 备用

        # 2. ATR (用于 ADX 和 Keltner Channels)
        # TR = max(high-low, abs(high-prev_close), abs(low-prev_close))
        df['tr0'] = df['high'] - df['low']
        df['tr1'] = (df['high'] - df['close'].shift(1)).abs()
        df['tr2'] = (df['low'] - df['close'].shift(1)).abs()
        df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
        df['atr_20'] = df['tr'].rolling(window=20).mean()  # 简单起见用 SMA

        # 3. ADX (14) - 趋势强度
        # +DM, -DM
        df['up_move'] = df['high'] - df['high'].shift(1)
        df['down_move'] = df['low'].shift(1) - df['low']

        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0.0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0.0)

        # 平滑
        alpha = 1 / 14
        df['plus_di'] = 100 * (df['plus_dm'].ewm(alpha=alpha, adjust=False).mean() / df['atr_20'])
        df['minus_di'] = 100 * (df['minus_dm'].ewm(alpha=alpha, adjust=False).mean() / df['atr_20'])

        dx = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']))
        df['adx'] = dx.ewm(alpha=alpha, adjust=False).mean()

        # 4. Squeeze Momentum (LazyBear version logic)
        # Bollinger Bands (20, 2.0)
        sma_20 = df['close'].rolling(window=20).mean()
        std_20 = df['close'].rolling(window=20).std()
        df['bb_upper'] = sma_20 + 2.0 * std_20
        df['bb_lower'] = sma_20 - 2.0 * std_20

        # Keltner Channels (20, 1.5 ATR)
        df['kc_upper'] = sma_20 + 1.5 * df['atr_20']
        df['kc_lower'] = sma_20 - 1.5 * df['atr_20']

        # Squeeze 状态: BB 也就是挤进 KC 内
        # Squeeze On (挤压中) = BB_Lower > KC_Lower AND BB_Upper < KC_Upper
        df['squeeze_on'] = (df['bb_lower'] > df['kc_lower']) & (df['bb_upper'] < df['kc_upper'])

        # Momentum (Linear Regression of price - avg(donchian midline + sma))
        # 简化版动量：当前价格 - SMA20
        df['momentum_val'] = df['close'] - sma_20
        # 为了更接近 LazyBear，可以用 linreg(close - avg(mean(high,low), sma), 20)，此处先用简化版

        # 5. Volume Ratio (当前成交量 / 过去 5 根均量)
        df['vol_ma_5'] = df['volume'].rolling(window=5).mean().shift(1)  # 不含当前
        df['vol_ratio'] = df['volume'] / df['vol_ma_5']

        # 清理中间列
        cols_to_keep = [
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'ema_21', 'ema_50', 'adx', 'plus_di', 'minus_di',
            'squeeze_on', 'momentum_val', 'vol_ratio'
        ]
        return df[cols_to_keep].dropna()