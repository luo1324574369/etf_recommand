import backtrader as bt


class ValuationDCAStrategy(bt.Strategy):
    params = (
        ('dca_amount', 10000),
        ('dca_freq', 20),
        ('valuation_period', 250),
        ('low_pctile', 30),
        ('high_pctile', 70),
        ('commission_rate', 0.0003),
    )

    def __init__(self):
        self.day_count = 0
        self.pe_values = {}
        for d in self.datas:
            self.pe_values[d] = []

    def next(self):
        self.day_count += 1

        for d in self.datas:
            close = d.close[0]
            self.pe_values[d].append(close)
            if len(self.pe_values[d]) > self.p.valuation_period:
                self.pe_values[d].pop(0)

        if self.day_count % self.p.dca_freq != 0:
            return

        for d in self.datas:
            prices = self.pe_values[d]
            if len(prices) < self.p.valuation_period:
                continue

            current = prices[-1]
            sorted_prices = sorted(prices)
            percentile = sum(1 for p in sorted_prices if p <= current) / len(sorted_prices) * 100

            if percentile <= self.p.low_pctile:
                multiplier = 2.0
            elif percentile >= self.p.high_pctile:
                multiplier = 0.5
            else:
                multiplier = 1.0

            invest_amount = self.p.dca_amount * multiplier
            price = d.close[0]
            if price <= 0:
                continue

            size = int(invest_amount / price / 100) * 100
            if size > 0 and self.broker.getcash() > invest_amount:
                self.buy(d, size=size)


def run_backtest(data_dict, initial_capital=1000000, commission_rate=0.0003,
                 start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import run_backtest as _run
    return _run(ValuationDCAStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)


def get_nav_curve(data_dict, initial_capital=1000000, commission_rate=0.0003,
                  start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import get_nav_curve as _nav
    return _nav(ValuationDCAStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)