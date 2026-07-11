from strategy.factors.base import FactorBase
from strategy.factors.trend import TrendFactor


class MarketTimingFilter:
    def __init__(self, benchmark_code="510300", period=60,
                 sector_breadth_enabled=True, sector_breadth_ratio=0.4,
                 sector_ma_period=60):
        self.benchmark_code = benchmark_code
        self.period = period
        self.sector_breadth_enabled = sector_breadth_enabled
        self.sector_breadth_ratio = sector_breadth_ratio
        self.sector_ma_period = sector_ma_period

    def filter(self, etf_codes, price_repo, current_date) -> list:
        prices = price_repo.get_daily_price(self.benchmark_code, end_date=current_date)
        if len(prices) < self.period:
            return etf_codes

        recent_prices = prices[-self.period:]
        close_prices = [p["close"] for p in recent_prices]
        ma = sum(close_prices) / len(close_prices)
        current_price = prices[-1]["close"]

        if current_price >= ma:
            return etf_codes

        if self.sector_breadth_enabled:
            above_ma_count = 0
            total_count = 0
            trend_factor = TrendFactor(period=self.sector_ma_period)

            for code in etf_codes:
                if code == self.benchmark_code:
                    continue
                sector_prices = price_repo.get_daily_price(code, end_date=current_date)
                if len(sector_prices) < self.sector_ma_period:
                    continue
                total_count += 1
                trend_value = trend_factor.calculate(code, sector_prices, current_date)
                if trend_value and trend_value.get("above_ma"):
                    above_ma_count += 1

            if total_count > 0:
                breadth_ratio = above_ma_count / total_count
                if breadth_ratio >= self.sector_breadth_ratio:
                    return etf_codes

        return []
