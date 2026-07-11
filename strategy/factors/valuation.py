from strategy.factors.base import FactorBase


class ValuationFactor(FactorBase):
    name = "valuation"
    description = "ETF valuation factor (PE, PB, PS, dividend yield)"

    def __init__(self, metric: str = "pe"):
        self.metric = metric
        self.name = f"valuation_{metric}"

    def calculate(self, code: str, price_data: list[dict], end_date: str, valuation_data: dict = None) -> float:
        if not valuation_data:
            return None
        val = valuation_data.get(self.metric)
        if val is None or val <= 0:
            return None
        return float(val)


class ValuationPercentileFactor(FactorBase):
    name = "valuation_percentile"
    description = "Valuation percentile factor (PE/PB percentile in history)"

    def __init__(self, metric: str = "pe"):
        self.metric = metric
        self.name = f"{metric}_percentile"

    def calculate(self, code: str, price_data: list[dict], end_date: str, percentile: float = None) -> float:
        if percentile is None:
            return None
        return float(percentile)
