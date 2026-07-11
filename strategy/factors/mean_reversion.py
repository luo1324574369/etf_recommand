from .base import FactorBase


class MeanReversionFactor(FactorBase):
    """均值回归因子：价格偏离均值的程度，偏离越大回归概率越高"""
    name = "mean_reversion"
    description = "Mean reversion factor based on price deviation from MA"

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        closes = [item["close"] for item in filtered]

        if len(closes) <= self.period:
            return None

        recent = closes[-self.period:]
        ma = sum(recent) / len(recent)
        current = closes[-1]

        if ma == 0:
            return None

        deviation = (current - ma) / ma
        return deviation
