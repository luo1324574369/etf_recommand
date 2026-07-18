import backtrader as bt
from strategy.constraints import StrategyConstraints


class DualMomentumStrategy(bt.Strategy):
    params = (
        ('lookback_short', 60),
        ('lookback_long', 120),
        ('top_n', 3),
        ('rebalance_freq', 20),
        ('commission_rate', 0.0003),
        ('min_momentum', 0),
        ('start_date', None),
        ('constraints', None),
    )

    def __init__(self):
        self.day_count = self.p.rebalance_freq - 1
        self.trade_log = []
        self.cumulative_pnl = 0.0
        self.prev_positions = {}
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'short_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_short),
                'long_ret': bt.indicators.RateOfChange(d.close, period=self.p.lookback_long),
            }
        if self.p.constraints is None:
            self.constraints = StrategyConstraints()
        elif isinstance(self.p.constraints, dict):
            self.constraints = StrategyConstraints(**self.p.constraints)
        else:
            self.constraints = self.p.constraints

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
            'cash_after': self.broker.get_cash(),
            'reason': reason,
        })

    def _get_current_positions_mv(self):
        """获取当前持仓市值"""
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

        current_date = self.data.datetime.date(0)
        total_value = self.broker.get_value()
        max_single_mv = total_value * self.constraints.max_position_pct / 100

        current_positions = self._get_current_positions_mv()
        pending_sell_amounts = 0.0

        for d in self.datas:
            pos = self.getposition(d)
            if pos.size <= 0:
                continue

            price = d.close[0]
            current_mv = pos.size * price

            if d._name not in selected_codes:
                sell_amount = current_mv
                ok, reason = self.constraints.can_sell(
                    d._name, price, sell_amount, pos.size, current_date,
                    current_positions=current_positions
                )
                if not ok:
                    continue
                rank = code_rank.get(d._name, (total_n,))[0] if total_n > 0 else 0
                reason_str = f"双动量排名第{rank}/{total_n}，调出持仓"
                sell_price = self.constraints.apply_slippage_sell(price)
                self._log_trade(d, '卖出', pos.size, sell_price, reason_str)
                self.constraints.record_turnover(d._name, sell_amount, current_date)
                pending_sell_amounts += sell_amount
                self.close(d)
                current_positions.pop(d._name, None)
            else:
                if current_mv > max_single_mv * 1.05:
                    excess_mv = current_mv - max_single_mv
                    sell_shares = int(excess_mv / price / 100) * 100
                    if sell_shares <= 0:
                        continue
                    sell_amount = sell_shares * price
                    ok, reason = self.constraints.can_sell(
                        d._name, price, sell_amount, pos.size, current_date,
                        current_positions=current_positions
                    )
                    if not ok:
                        continue
                    rank, score, short_ret, long_ret = code_rank.get(d._name, (0, 0, 0, 0))
                    reason_str = f"双动量排名第{rank}/{total_n}，超配减仓（当前{current_mv/total_value*100:.1f}%→目标{self.constraints.max_position_pct}%）"
                    sell_price = self.constraints.apply_slippage_sell(price)
                    self._log_trade(d, '卖出', sell_shares, sell_price, reason_str)
                    self.constraints.record_turnover(d._name, sell_amount, current_date)
                    pending_sell_amounts += sell_amount
                    self.sell(d, size=sell_shares, price=sell_price)
                    current_positions[d._name] = current_mv - sell_amount

        effective_cash = self.broker.get_cash() + pending_sell_amounts

        for d in selected:
            price = d.close[0]
            if price <= 0:
                continue
            pos = self.getposition(d)
            current_mv = current_positions.get(d._name, 0)
            buy_budget = max(0, max_single_mv - current_mv)

            if buy_budget <= 0:
                continue

            buy_price = self.constraints.apply_slippage_buy(price)
            target_size = int(buy_budget / buy_price / 100) * 100
            if target_size <= 0:
                continue
            buy_amount = target_size * buy_price

            if buy_amount > effective_cash + 1e-6:
                target_size = int(effective_cash / buy_price / 100) * 100
                if target_size <= 0:
                    continue
                buy_amount = target_size * buy_price

            ok, reason = self.constraints.can_buy(
                d._name, buy_price, buy_amount, current_positions, total_value,
                current_date, effective_cash=effective_cash
            )
            if not ok:
                continue
            ok_t, reason_t = self.constraints.check_turnover(
                buy_amount, total_value, current_date
            )
            if not ok_t:
                continue

            rank, score, short_ret, long_ret = code_rank.get(d._name, (0, 0, 0, 0))
            reason_str = f"双动量排名第{rank}/{total_n}，综合得分{score:.2f}，短周期动量{short_ret:.1f}%，长周期动量{long_ret:.1f}%"
            self._log_trade(d, '买入', target_size, buy_price, reason_str)
            self.constraints.record_buy(d._name, current_date)
            self.constraints.record_turnover(d._name, buy_amount, current_date)
            self.buy(d, size=target_size, price=buy_price)
            effective_cash -= buy_amount
            current_positions[d._name] = current_mv + buy_amount

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
