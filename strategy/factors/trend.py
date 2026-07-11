from .base import FactorBase


class TrendFactor(FactorBase):
    name = "trend"
    description = "Moving average trend factor"

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        closes = [item["close"] for item in filtered]

        if len(closes) <= self.period + 5:
            return None

        ma_current = sum(closes[-self.period:]) / self.period
        ma_5_ago = sum(closes[-self.period - 5:-5]) / self.period
        current_price = closes[-1]

        ma_rising = ma_current > ma_5_ago

        return {
            "ma_value": ma_current,
            "price": current_price,
            "above_ma": current_price > ma_current,
            "ma_rising": ma_rising,
        }
