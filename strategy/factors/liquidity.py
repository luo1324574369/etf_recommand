from .base import FactorBase


class LiquidityFactor(FactorBase):
    name = "liquidity"
    description = "Average daily amount (liquidity) factor"

    def __init__(self, period: int = 20):
        self.period = period

    def calculate(self, code: str, price_data: list[dict], end_date: str):
        filtered = [item for item in price_data if item["trade_date"] <= end_date]
        if len(filtered) < self.period:
            return None

        recent = filtered[-self.period:]
        amounts = [item.get("amount", 0) for item in recent if item.get("amount")]
        if not amounts:
            return None

        avg_amount = sum(amounts) / len(amounts)
        return avg_amount
