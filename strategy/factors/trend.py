from .base import FactorBase


class TrendFactor(FactorBase):
    name = "trend"
    description = "Moving average trend factor"

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        closes = [item["close"] for item in filtered]

        if len(closes) <= self.period:
            return None

        ma_closes = closes[-self.period - 1:-1]
        ma = sum(ma_closes) / self.period
        current_price = closes[-1]

        return {
            "ma_value": ma,
            "price": current_price,
            "above_ma": current_price > ma,
        }
