from strategy.filters.base import FilterBase


class TrendFilter(FilterBase):
    name = "trend_filter"

    def __init__(self, ma_period: int = 20, require_rising: bool = False):
        self.ma_period = ma_period
        self.require_rising = require_rising

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        trend = factor_values.get("trend")
        if trend is None or not isinstance(trend, dict):
            return (False, 0.0)
        if trend.get("above_ma") is not True:
            return (False, 0.0)
        if self.require_rising and trend.get("ma_rising") is not True:
            return (False, 0.5)
        return (True, 1.0)
