class BacktestMetrics:

    @staticmethod
    def calculate(daily_nav) -> dict:
        return {
            "total_return": None,
            "annual_return": None,
            "max_drawdown": None,
            "sharpe_ratio": None,
            "win_rate": None,
            "trade_count": None,
            "profit_factor": None,
            "note": "Metrics calculation not implemented yet",
        }

    @staticmethod
    def max_drawdown(daily_nav) -> None:
        return None

    @staticmethod
    def sharpe_ratio(daily_returns, risk_free_rate=0.03) -> None:
        return None
