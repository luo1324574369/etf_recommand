import backtrader as bt


class DualMomentumStrategy(bt.Strategy):
    params = (
        ('lookback_short', 60),
        ('lookback_long', 120),
        ('top_n', 3),
        ('rebalance_freq', 20),
        ('commission_rate', 0.0003),
        ('min_momentum', 0),
    )

    def __init__(self):
        self.day_count = 0
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'short_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_short),
                'long_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_long),
            }

    def next(self):
        self.day_count += 1
        if self.day_count % self.p.rebalance_freq != 0:
            return

        momentum_scores = []
        for d in self.datas:
            short_ret = self.inds[d]['short_ret'][0]
            long_ret = self.inds[d]['long_ret'][0]
            if short_ret is None or long_ret is None:
                continue
            score = 0.5 * short_ret + 0.5 * long_ret
            if score > self.p.min_momentum:
                momentum_scores.append((d, score))

        momentum_scores.sort(key=lambda x: x[1], reverse=True)
        selected = [d for d, _ in momentum_scores[:self.p.top_n]]
        selected_codes = {d._name for d in selected}

        for d in self.datas:
            pos = self.getposition(d)
            if d._name not in selected_codes and pos.size > 0:
                self.close(d)

        if not selected:
            return

        total_value = self.broker.get_value() * 0.9
        per_value = total_value / len(selected)

        for d in selected:
            price = d.close[0]
            if price <= 0:
                continue
            pos = self.getposition(d)
            target_size = int(per_value / price / 100) * 100
            if target_size > pos.size:
                self.buy(d, size=target_size - pos.size)
            elif target_size < pos.size:
                self.sell(d, size=pos.size - target_size)


def run_backtest(data_dict, initial_capital=1000000, commission_rate=0.0003,
                 start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import run_backtest as _run
    return _run(DualMomentumStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)


def get_nav_curve(data_dict, initial_capital=1000000, commission_rate=0.0003,
                  start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import get_nav_curve as _nav
    return _nav(DualMomentumStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)