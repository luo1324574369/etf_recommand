"""
策略约束模块
统一管理卖空、仓位、滑点、T+1、换手率等约束条件
"""
from typing import Dict, Optional, Tuple
from datetime import date


class StrategyConstraints:
    """策略约束集合

    参数:
        long_only: 单向做多，不允许做空
        max_positions: 最大持仓数量
        min_positions: 最少持仓数量
        max_position_pct: 单仓位上限(%)
        max_total_exposure_pct: 总仓位上限(%)，所有持仓总市值/总资金
        slippage_rate: 滑点率(%)，买入上浮，卖出下浮
        t_plus_one: T+1约束，当日买入不能当日卖出
        min_trade_amount: 最低交易金额(元)
        max_monthly_turnover: 月度换手率上限(%)，每月调仓金额/总市值
    """

    def __init__(
        self,
        long_only: bool = True,
        max_positions: int = 5,
        min_positions: int = 0,
        max_position_pct: float = 40.0,
        max_total_exposure_pct: float = 95.0,
        slippage_rate: float = 0.1,
        t_plus_one: bool = True,
        min_trade_amount: float = 5000.0,
        max_monthly_turnover: float = 100.0,
    ):
        self.long_only = long_only
        self.max_positions = max_positions
        self.min_positions = min_positions
        self.max_position_pct = max_position_pct
        self.max_total_exposure_pct = max_total_exposure_pct
        self.slippage_rate = slippage_rate
        self.t_plus_one = t_plus_one
        self.min_trade_amount = min_trade_amount
        self.max_monthly_turnover = max_monthly_turnover

        self._buy_dates: Dict[str, date] = {}
        self._monthly_turnover: Dict[str, float] = {}
        self._current_month: Optional[str] = None

    def apply_slippage_buy(self, price: float) -> float:
        """买入价上浮滑点"""
        return price * (1 + self.slippage_rate / 100)

    def apply_slippage_sell(self, price: float) -> float:
        """卖出价下浮滑点"""
        return price * (1 - self.slippage_rate / 100)

    def can_buy(
        self,
        code: str,
        price: float,
        amount: float,
        current_positions: Dict[str, float],
        total_value: float,
        current_date: date,
        effective_cash: float = None,
    ) -> Tuple[bool, str]:
        """检查是否可以买入

        Args:
            code: ETF代码
            price: 当前价格
            amount: 买入金额
            current_positions: 当前持仓 {code: 市值}
            total_value: 总市值
            current_date: 当前日期
            effective_cash: 可用现金（含待释放卖出资金），None表示不检查

        Returns:
            (是否可以买入, 原因)
        """
        if amount <= 0:
            return False, "买入金额为0"

        if amount < self.min_trade_amount:
            return False, f"买入金额{amount:.0f}元低于最低交易金额{self.min_trade_amount:.0f}元"

        current_mv = current_positions.get(code, 0)
        new_mv = current_mv + amount
        max_mv = total_value * self.max_position_pct / 100

        if new_mv > max_mv:
            return False, f"买入后市值{new_mv:.0f}元超过单仓上限{max_mv:.0f}元({self.max_position_pct}%)"

        current_count = sum(1 for v in current_positions.values() if v > 0)
        if code not in current_positions or current_positions.get(code, 0) <= 0:
            if current_count >= self.max_positions:
                return False, f"持仓数量{current_count}已达上限{self.max_positions}"

        total_mv = sum(current_positions.values())
        if total_mv + amount > total_value * self.max_total_exposure_pct / 100 + 1e-6:
            new_pct = (total_mv + amount) / total_value * 100
            return False, f"总仓位将达{new_pct:.1f}%，超过上限{self.max_total_exposure_pct}%"

        if effective_cash is not None and amount > effective_cash + 1e-6:
            return False, f"买入金额{amount:.0f}超过可用现金{effective_cash:.0f}"

        return True, ""

    def can_sell(
        self,
        code: str,
        price: float,
        amount: float,
        current_position_size: int,
        current_date: date,
        current_positions: Dict[str, float] = None,
    ) -> Tuple[bool, str]:
        """检查是否可以卖出

        Args:
            code: ETF代码
            price: 当前价格
            amount: 卖出金额
            current_position_size: 当前持仓数量(股)
            current_date: 当前日期
            current_positions: 当前持仓 {code: 市值}，用于检查最少持仓数

        Returns:
            (是否可以卖出, 原因)
        """
        if amount <= 0:
            return False, "卖出金额为0"

        if self.t_plus_one:
            buy_date = self._buy_dates.get(code)
            if buy_date and buy_date >= current_date:
                return False, "T+1约束，当日买入不能当日卖出"

        # 检查最少持仓数量：如果本次卖出会清仓该标的，需确保持仓数不低于下限
        if self.min_positions > 0 and current_positions is not None:
            current_count = sum(1 for v in current_positions.values() if v > 0)
            is_full_close = current_position_size * price <= amount + 1
            if is_full_close and current_count - 1 < self.min_positions:
                return False, f"卖出后持仓数{current_count - 1}低于下限{self.min_positions}"

        return True, ""

    def record_buy(self, code: str, trade_date: date) -> None:
        """记录买入日期，用于T+1检查"""
        self._buy_dates[code] = trade_date

    def check_turnover(
        self,
        trade_amount: float,
        total_value: float,
        current_date: date,
    ) -> Tuple[bool, str]:
        """检查月度换手率约束

        Args:
            trade_amount: 本次交易金额
            total_value: 总市值
            current_date: 当前日期

        Returns:
            (是否可以交易, 原因)
        """
        month_key = current_date.strftime("%Y-%m")

        if month_key != self._current_month:
            self._current_month = month_key
            self._monthly_turnover = {}

        current_turnover = sum(self._monthly_turnover.values())
        new_turnover = current_turnover + trade_amount
        turnover_pct = new_turnover / total_value * 100

        if turnover_pct > self.max_monthly_turnover:
            return False, f"月度换手率{turnover_pct:.1f}%超过上限{self.max_monthly_turnover}%"

        return True, ""

    def record_turnover(self, code: str, amount: float, trade_date: date = None) -> None:
        """记录月度换手率"""
        if trade_date:
            month_key = trade_date.strftime("%Y-%m")
            if month_key != self._current_month:
                self._current_month = month_key
                self._monthly_turnover = {}
        self._monthly_turnover[code] = self._monthly_turnover.get(code, 0) + amount

    def reset(self) -> None:
        """重置状态"""
        self._buy_dates = {}
        self._monthly_turnover = {}
        self._current_month = None
