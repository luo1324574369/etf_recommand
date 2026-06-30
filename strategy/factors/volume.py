from .base import FactorBase


class VolumeFactor(FactorBase):
    name = "volume"
    description = "Volume ratio factor (short avg / long avg)"

    def __init__(self, short_period: int = 5, long_period: int = 20):
        self.short_period = short_period
        self.long_period = long_period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        volumes = [item["volume"] for item in filtered]

        if len(volumes) < self.short_period + self.long_period:
            return None

        short_avg = sum(volumes[-self.short_period:]) / self.short_period
        long_avg = sum(volumes[-self.short_period - self.long_period:-self.short_period]) / self.long_period

        if long_avg == 0:
            return None

        return short_avg / long_avg
