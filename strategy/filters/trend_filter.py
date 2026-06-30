from strategy.filters.base import FilterBase


class TrendFilter(FilterBase):
    name = "trend_filter"

    def __init__(self, ma_period: int = 20):
        self.ma_period = ma_period

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        trend = factor_values.get("trend")
        if trend is None or not isinstance(trend, dict):
            return (False, 0.0)
        if trend.get("above_ma") is True:
            return (True, 1.0)
        return (False, 0.0)
