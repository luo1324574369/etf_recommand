import backtrader as bt
from strategy.constraints import StrategyConstraints


class ValuationDCAStrategy(bt.Strategy):
    params = (
        ('dca_amount', 10000),
        ('dca_freq', 20),
        ('valuation_period', 250),
        ('low_pctile', 30),
        ('high_pctile', 70),
        ('commission_rate', 0.0003),
        ('start_date', None),
        ('constraints', None),
    )

    def __init__(self):
        self.day_count = 0
        self.pe_values = {}
        self.trade_log = []
        self.cumulative_pnl = 0.0
        for d in self.datas:
            self.pe_values[d] = []
        if self.p.constraints is None:
            self.constraints = StrategyConstraints()
        elif isinstance(self.p.constraints, dict):
            self.constraints = StrategyConstraints(**self.p.constraints)
        else:
            self.constraints = self.p.constraints

    def _log_trade(self, d, direction, size, price, reason):
        amount = size * price
        fee = amount * self.p.commission_rate
        position_after = self.getposition(d).size + size
        self.trade_log.append({
            'date': self.data.datetime.date(0).isoformat(),
            'code': d._name,
            'direction': '买入',
            'quantity': size,
            'price': price,
            'amount': amount,
            'fee': fee,
            'position_after': position_after,
            'pnl': 0.0,
            'cumulative_pnl': self.cumulative_pnl,
            'reason': reason,
        })

    def _get_current_positions_mv(self):
        positions = {}
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size > 0:
                positions[d._name] = pos.size * d.close[0]
        return positions

    def next(self):
        if self.p.start_date:
            current_date = self.data.datetime.date(0)
            if current_date < self.p.start_date:
                return

        self.day_count += 1

        for d in self.datas:
            close = d.close[0]
            self.pe_values[d].append(close)
            if len(self.pe_values[d]) > self.p.valuation_period:
                self.pe_values[d].pop(0)

        if self.day_count % self.p.dca_freq != 0:
            return

        current_date = self.data.datetime.date(0)
        total_value = self.broker.get_value()
        current_positions = self._get_current_positions_mv()

        for d in self.datas:
            prices = self.pe_values[d]
            if len(prices) < self.p.valuation_period:
                continue

            current = prices[-1]
            sorted_prices = sorted(prices)
            percentile = sum(1 for p in sorted_prices if p <= current) / len(sorted_prices) * 100

            if percentile <= self.p.low_pctile:
                multiplier = 2.0
                reason = f"PE百分位{percentile:.1f}%，低于{self.p.low_pctile:.0f}%阈值，双倍定投"
            elif percentile >= self.p.high_pctile:
                multiplier = 0.5
                reason = f"PE百分位{percentile:.1f}%，高于{self.p.high_pctile:.0f}%阈值，减半定投"
            else:
                multiplier = 1.0
                reason = f"PE百分位{percentile:.1f}%，正常定投"

            invest_amount = self.p.dca_amount * multiplier
            price = d.close[0]
            if price <= 0:
                continue

            buy_price = self.constraints.apply_slippage_buy(price)
            size = int(invest_amount / buy_price / 100) * 100
            buy_amount = size * buy_price

            if size <= 0 or self.broker.getcash() < buy_amount:
                continue

            ok, reason_c = self.constraints.can_buy(
                d._name, buy_price, buy_amount, current_positions, total_value, current_date
            )
            if not ok:
                continue
            ok_t, reason_t = self.constraints.check_turnover(
                buy_amount, total_value, current_date
            )
            if not ok_t:
                continue

            self._log_trade(d, '买入', size, buy_price, reason)
            self.constraints.record_buy(d._name, current_date)
            self.constraints.record_turnover(d._name, buy_amount, current_date)
            self.buy(d, size=size, price=buy_price)
            current_positions = self._get_current_positions_mv()


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
