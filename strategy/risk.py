# strategy/risk.py
from config.settings import settings


class RiskManager:
    """
    输入: 账户权益, AI分数, 入场价, 止损价
    输出: (is_allowed, quantity, leverage, reason)
    """

    def calculate_position_size(self, equity: float, ai_score: float,
                                entry_price: float, stop_loss_price: float):

        # 1. 动态保证金 (V8.3 8.1)
        # 默认 10% 仓位，保底 50U
        base_margin = max(50.0, equity * 0.10)

        # AI 增强 (Score > 85 放大 1.2倍)
        if ai_score >= 85:
            base_margin *= 1.2

        # 2. 止损距离计算
        # Long: entry - stop
        price_dist = entry_price - stop_loss_price
        if price_dist <= 0:
            return False, 0, 1, "Stop price >= Entry price for Long"

        stop_dist_pct = price_dist / entry_price

        # 3. 杠杆计算 (V8.3 未硬性规定杠杆公式，通常根据止损距离倒推)
        # 假设我们希望止损时亏损不超过 margin 的 X%?
        # 文档 8.2: risk_amount = base_margin * leverage * stop_dist_pct
        # 约束: risk_amount <= equity * 0.03

        # 这里的核心是确定 leverage。为了安全，我们反推最大允许杠杆。
        # Max Risk = equity * 0.03
        # margin * leverage * stop_dist_pct <= Max Risk
        # leverage <= Max Risk / (margin * stop_dist_pct)

        max_risk_budget = equity * 0.03

        if stop_dist_pct == 0:
            return False, 0, 1, "Zero stop distance"

        max_leverage_calc = max_risk_budget / (base_margin * stop_dist_pct)

        # 取整并限制最大杠杆 (例如 20x)
        final_leverage = int(min(max_leverage_calc, 20))

        if final_leverage < 1:
            return False, 0, 1, f"Risk budget exceeded. Max Lev < 1. Risk=${base_margin * 1 * stop_dist_pct:.2f} > Budget=${max_risk_budget:.2f}"

        # 4. 计算最终下单数量 (合约张数/币数)
        # position_value = margin * leverage
        # quantity = position_value / entry_price
        position_value = base_margin * final_leverage
        quantity = position_value / entry_price

        return True, quantity, final_leverage, f"Risk OK. Budget=${max_risk_budget:.2f}"