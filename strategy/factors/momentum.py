from .base import FactorBase


class MomentumFactor(FactorBase):
    name = "momentum"
    description = "Period price momentum factor"

    def __init__(self, period: int = 10):
        self.period = period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        closes = [item["close"] for item in filtered]

        if len(closes) <= self.period:
            return None

        past = closes[-self.period - 1]
        current = closes[-1]

        if past == 0:
            return None

        return (current - past) / past
