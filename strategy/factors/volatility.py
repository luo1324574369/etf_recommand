from strategy.factors.base import FactorBase


class VolatilityFactor(FactorBase):
    def __init__(self, period=20):
        self.name = "volatility"
        self.period = period

    def calculate(self, code, price_data, end_date) -> dict:
        if len(price_data) < self.period:
            return {"volatility": 0, "is_high_vol": False}

        recent = price_data[-self.period:]
        returns = []
        for i in range(1, len(recent)):
            prev = recent[i-1]["close"]
            curr = recent[i]["close"]
            if prev > 0:
                returns.append((curr - prev) / prev)

        if len(returns) < 2:
            return {"volatility": 0, "is_high_vol": False}

        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        volatility = (variance ** 0.5) * (252 ** 0.5)

        return {
            "volatility": volatility,
            "is_high_vol": volatility > 0.3,
        }
