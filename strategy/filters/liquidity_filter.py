from strategy.filters.base import FilterBase


class LiquidityFilter(FilterBase):
    name = "liquidity_filter"

    def __init__(self, min_avg_amount: float = 50000000):
        self.min_avg_amount = min_avg_amount

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        liquidity = factor_values.get("liquidity")
        if liquidity is None:
            return (False, 0.0)
        if liquidity >= self.min_avg_amount:
            return (True, liquidity)
        return (False, liquidity)
