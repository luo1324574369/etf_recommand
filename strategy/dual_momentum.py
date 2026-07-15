import backtrader as bt


class DualMomentumStrategy(bt.Strategy):
    params = (
        ('lookback_short', 60),
        ('lookback_long', 120),
        ('top_n', 3),
        ('rebalance_freq', 20),
        ('commission_rate', 0.0003),
        ('min_momentum', 0),
        ('start_date', None),  # 回测起始日，None表示不限
    )

    def __init__(self):
        self.day_count = 0
        self.trade_log = []
        self.cumulative_pnl = 0.0
        self.prev_positions = {}
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'short_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_short),
                'long_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_long),
            }

    def _log_trade(self, d, direction, size, price, reason):
        amount = size * price
        fee = amount * self.p.commission_rate
        pos = self.getposition(d)
        if direction == '买入':
            position_after = pos.size + size
            pnl = 0.0
        else:
            position_after = pos.size - size
            if pos.price > 0:
                pnl = (price - pos.price) * size
            else:
                pnl = 0.0
        self.cumulative_pnl += pnl - fee
        self.trade_log.append({
            'date': self.data.datetime.date(0).isoformat(),
            'code': d._name,
            'direction': direction,
            'quantity': size,
            'price': price,
            'amount': amount,
            'fee': fee,
            'position_after': position_after,
            'pnl': pnl,
            'cumulative_pnl': self.cumulative_pnl,
            'reason': reason,
        })

    def next(self):
        # 回测起始日之前不交易
        if self.p.start_date:
            current_date = self.data.datetime.date(0)
            if current_date < self.p.start_date:
                return

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
                momentum_scores.append((d, score, short_ret, long_ret))

        momentum_scores.sort(key=lambda x: x[1], reverse=True)
        total_n = len(momentum_scores)
        selected = [item[0] for item in momentum_scores[:self.p.top_n]]
        selected_codes = {d._name for d in selected}

        code_rank = {}
        for rank, (d, score, short_ret, long_ret) in enumerate(momentum_scores, 1):
            code_rank[d._name] = (rank, score, short_ret, long_ret)

        for d in self.datas:
            pos = self.getposition(d)
            if d._name not in selected_codes and pos.size > 0:
                rank = code_rank.get(d._name, (total_n,))[0] if total_n > 0 else 0
                reason = f"双动量排名第{rank}/{total_n}，调出持仓"
                price = d.close[0]
                self._log_trade(d, '卖出', pos.size, price, reason)
                self.close(d)

        if not selected:
            self.prev_positions = {d._name: self.getposition(d).size for d in self.datas}
            return

        total_value = self.broker.get_value() * 0.9
        per_value = total_value / len(selected)

        for d in selected:
            price = d.close[0]
            if price <= 0:
                continue
            pos = self.getposition(d)
            target_size = int(per_value / price / 100) * 100
            rank, score, short_ret, long_ret = code_rank.get(d._name, (0, 0, 0, 0))
            if target_size > pos.size:
                buy_size = target_size - pos.size
                reason = f"双动量排名第{rank}/{total_n}，综合得分{score:.2f}，短周期动量{short_ret:.1f}%，长周期动量{long_ret:.1f}%"
                self._log_trade(d, '买入', buy_size, price, reason)
                self.buy(d, size=buy_size)
            elif target_size < pos.size:
                sell_size = pos.size - target_size
                reason = f"双动量排名第{rank}/{total_n}，仓位调整"
                self._log_trade(d, '卖出', sell_size, price, reason)
                self.sell(d, size=sell_size)

        self.prev_positions = {d._name: self.getposition(d).size for d in self.datas}


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