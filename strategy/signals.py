# strategy/signals.py
from config.logging_config import setup_logger

logger = setup_logger("signal_detector")


class SignalDetector:
    """
    无状态信号检测器
    输入: current_indicators (dict), prev_indicators (dict)
    输出: (bool, reason_code, reason_text)
    """

    @staticmethod
    def check_setup_b_long(curr: dict, prev: dict) -> tuple:
        """
        Setup B 做多条件 (V8.3 6.2):
        1. 趋势: ADX > 25 且 +DI > -DI
        2. 动量: Squeeze 释放 (当前 False, 前一个 True) OR 动量柱由负转正
           (简化版: 只要动量强劲且方向正确，配合 Squeeze 状态)
           严格版: Momentum > 0 AND Prev_Momentum < 0
        3. 量能: VolRatio > 1.5
        """
        # 1. 趋势检查
        adx_ok = curr['adx'] > 25
        trend_ok = curr['di_plus'] > curr['di_minus']

        if not (adx_ok and trend_ok):
            return False, None, "Trend weak"

        # 2. 动量检查 (挤压释放 或 动量爆发)
        # Squeeze 刚刚释放: 前一根是挤压(True)，当前不是(False)
        squeeze_release = (prev['squeeze_on'] is True) and (curr['squeeze_on'] is False)

        # 动量金叉: 前一根 < 0，当前 > 0
        momentum_flip = (prev['momentum'] < 0) and (curr['momentum'] > 0)

        # 只要满足其一即可，或者要求组合
        if not (squeeze_release or momentum_flip):
            return False, None, "No momentum trigger"

        # 3. 量能检查 (V8.3 要求 VolRatio > 1.5)
        # 注意: 实际交易中 1.5 可能太高，可配置化，这里按文档写死
        vol_ok = curr['vol_ratio'] > 1.5
        if not vol_ok:
            return False, None, f"Low volume ({curr['vol_ratio']})"

        # 4. 构造理由
        trigger_type = "Squeeze Release" if squeeze_release else "Momemtum Flip"
        reason = f"{trigger_type}, ADX={curr['adx']}, Vol={curr['vol_ratio']}"

        return True, "SETUP_B_LONG", reason