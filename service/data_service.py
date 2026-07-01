from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from strategy.factors.momentum import MomentumFactor
from strategy.factors.trend import TrendFactor
from strategy.factors.volume import VolumeFactor


class DataService:
    def __init__(self, db):
        self.db = db
        self.etf_repo = ETFRepository(db)
        self.price_repo = PriceRepository(db)

    def get_etf(self, code: str):
        return self.etf_repo.get_etf(code)

    def list_etfs(self, active_only: bool = True):
        return self.etf_repo.list_etfs(active_only=active_only)

    def get_daily_price(self, code: str):
        return self.price_repo.get_daily_price(code)

    def get_latest_price(self, code: str):
        return self.price_repo.get_latest_price(code)

    def get_recent_prices(self, code: str, days: int = 30):
        all_prices = self.price_repo.get_daily_price(code)
        return list(reversed(all_prices[-days:]))

    def calculate_factors(self, code: str, as_of_date: str = None):
        all_prices = self.price_repo.get_daily_price(code)
        if not all_prices:
            return {"momentum": None, "trend": None, "volume": None}

        latest_date = as_of_date or all_prices[-1]["trade_date"]

        momentum_factor = MomentumFactor(period=20)
        trend_factor = TrendFactor(period=20)
        volume_factor = VolumeFactor(short_period=5, long_period=20)

        return {
            "momentum": momentum_factor.calculate(code, all_prices, latest_date),
            "trend": trend_factor.calculate(code, all_prices, latest_date),
            "volume": volume_factor.calculate(code, all_prices, latest_date),
        }

    def get_etf_detail(self, code: str):
        etf = self.etf_repo.get_etf(code)
        if not etf:
            return None

        all_prices = self.price_repo.get_daily_price(code)
        recent_prices = list(reversed(all_prices[-30:]))
        latest_date = all_prices[-1]["trade_date"] if all_prices else None

        factors = {"momentum": None, "trend": None, "volume": None}
        if latest_date:
            factors = self.calculate_factors(code, latest_date)

        return {
            "etf": etf,
            "recent_prices": recent_prices,
            "factors": factors,
        }
