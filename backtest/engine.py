class BacktestEngine:

    def __init__(self, strategy, price_repo, initial_capital=1000000, commission_rate=0.0003):
        self.strategy = strategy
        self.price_repo = price_repo
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.positions = {}
        self.cash = initial_capital
        self.trade_history = []
        self.daily_nav = []

    def run(self, etf_codes, start_date, end_date) -> dict:
        raise NotImplementedError("回测逻辑待实现，这是框架占位")

    def _rebalance(self, trade_date, signals):
        raise NotImplementedError

    def _calculate_nav(self, trade_date):
        raise NotImplementedError

    def get_summary(self) -> dict:
        position_value = 0
        for code, pos in self.positions.items():
            last_price = pos.get("last_price", 0)
            position_value += pos.get("shares", 0) * last_price
        final_capital = self.cash + position_value
        return {
            "initial_capital": self.initial_capital,
            "final_capital": final_capital,
            "trade_count": len(self.trade_history),
            "status": "not_implemented",
        }
