"""多因子轮动策略

动量 + 估值 + 低波动 三因子等权轮动。
复用 scoring.py 的因子计算和合成能力。
"""
import backtrader as bt
import pandas as pd
import numpy as np
from typing import Dict, Optional

from strategy.constraints import StrategyConstraints


class MultiFactorStrategy(bt.Strategy):
    params = (
        ('lookback_momentum', 60),
        ('lookback_volatility', 60),
        ('top_n', 3),
        ('rebalance_freq', 20),
        ('commission_rate', 0.0003),
        ('start_date', None),
        ('constraints', None),
        ('valuation_repo', None),
        ('factor_weights', None),  # None=等权
    )

    def __init__(self):
        self.day_count = self.p.rebalance_freq - 1
        self.trade_log = []
        self.cumulative_pnl = 0.0
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {
                'momentum': bt.indicators.RateOfChange(d.close, period=self.p.lookback_momentum),
                'volatility': bt.indicators.StdDev(d.close, period=self.p.lookback_volatility),
            }
        if self.p.constraints is None:
            self.constraints = StrategyConstraints()
        elif isinstance(self.p.constraints, dict):
            self.constraints = StrategyConstraints(**self.p.constraints)
        else:
            self.constraints = self.p.constraints

        # code_to_sector默认为空，由外部设置
        self.code_to_sector = {}

        # 换手率追踪：每个调仓周期累加买入金额
        self._turnover_records = []  # [{'date': str, 'buy_amount': float, 'total_value': float}]
        self._current_period_buys = 0.0  # 当前调仓周期累计买入金额
        self._current_period_date = None  # 当前调仓日

    def _log_trade(self, d, direction, size, price, reason):
        amount = size * price
        fee = amount * self.p.commission_rate
        pos = self.getposition(d)
        if direction == '买入':
            position_after = pos.size + size
            pnl = 0.0
            # 累加买入金额到当前周期
            self._current_period_buys += amount
        else:
            position_after = pos.size - size
            if pos.price > 0:
                pnl = (price - pos.price) * size
            else:
                pnl = 0.0
        self.cumulative_pnl += pnl - fee
        cash_after = self.broker.get_cash()
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
            'cash_after': cash_after,
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

    def _get_pe_percentile(self, code: str) -> Optional[float]:
        """获取ETF当前PE历史百分位"""
        if self.p.valuation_repo is None:
            return None
        try:
            pe_history = self.p.valuation_repo.get_pe_history(code)
            if not pe_history:
                return None
            current_pe = pe_history[-1].get('pe')
            if current_pe is None or current_pe <= 0:
                return None
            all_pes = [h['pe'] for h in pe_history if h.get('pe') and h['pe'] > 0]
            if not all_pes:
                return None
            rank = sum(1 for pe in all_pes if pe <= current_pe)
            return rank / len(all_pes) * 100
        except Exception:
            return None

    def _compute_scores(self):
        """计算所有ETF的多因子综合得分"""
        etf_factors = {}
        etf_raw = {}
        for d in self.datas:
            code = d._name
            momentum = self.inds[d]['momentum'][0]
            volatility = self.inds[d]['volatility'][0]
            if momentum is None or volatility is None:
                continue

            pe_pct = self._get_pe_percentile(code)

            factors = {}
            factors['momentum_60d'] = float(momentum) if momentum is not None else None
            factors['volatility_60d'] = float(volatility) * 100 if volatility is not None else None
            if pe_pct is not None:
                factors['pe_percentile'] = pe_pct

            # 只保留动量和波动率都有值的ETF
            if factors['momentum_60d'] is None or factors['volatility_60d'] is None:
                continue

            etf_factors[code] = factors
            etf_raw[code] = {
                'momentum': float(momentum) if momentum else 0,
                'pe_pct': pe_pct if pe_pct else 0,
                'volatility': float(volatility) * 100 if volatility else 0,
            }

        if not etf_factors:
            return [], {}, {}

        # zscore标准化
        from strategy.scoring import zscore_normalize, equal_weight_score

        # 确定可用因子（所有ETF都有的）
        available_factors = ['momentum_60d', 'volatility_60d']
        if all('pe_percentile' in f for f in etf_factors.values()):
            available_factors.append('pe_percentile')

        zscores = zscore_normalize(etf_factors, factor_names=available_factors)
        scores = equal_weight_score(zscores, factor_names=available_factors)

        sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [code for code, score in sorted_codes[:self.p.top_n]]

        return selected, scores, etf_raw

    def next(self):
        if self.p.start_date:
            current_date = self.data.datetime.date(0)
            if current_date < self.p.start_date:
                return

        # 换手率追踪：在调仓日入口处记录上一周期的换手
        current_date = self.data.datetime.date(0)
        current_iso = current_date.isoformat()
        if self._current_period_date is not None and self.day_count % self.p.rebalance_freq == 0:
            total_value = self.broker.get_value()
            self._turnover_records.append({
                'date': self._current_period_date,
                'buy_amount': self._current_period_buys,
                'total_value': total_value,
            })
            self._current_period_buys = 0.0
            self._current_period_date = current_iso
        elif self._current_period_date is None:
            self._current_period_date = current_iso

        self.day_count += 1
        if self.day_count % self.p.rebalance_freq != 0:
            return

        selected_codes, scores, raw_factors = self._compute_scores()
        if not selected_codes:
            return

        selected_set = set(selected_codes)
        total_n = len(scores)
        code_rank = {code: i + 1 for i, (code, _) in enumerate(
            sorted(scores.items(), key=lambda x: x[1], reverse=True)
        )}

        current_date = self.data.datetime.date(0)
        total_value = self.broker.get_value()
        max_single_mv = total_value * self.constraints.max_position_pct / 100
        current_positions = self._get_current_positions_mv()
        pending_sell_amounts = 0.0

        # 阶段1：卖出
        # 1a. 清仓：不在新top_n的持仓
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size <= 0:
                continue
            price = d.close[0]
            current_mv = pos.size * price

            if d._name not in selected_set:
                sell_amount = current_mv
                ok, reason = self.constraints.can_sell(
                    d._name, price, sell_amount, pos.size, current_date,
                    current_positions=current_positions
                )
                if not ok:
                    continue
                rank = code_rank.get(d._name, total_n)
                score = scores.get(d._name, 0)
                reason_str = f"多因子排名第{rank}/{total_n}，调出持仓（综合得分{score:.2f}）"
                sell_price = self.constraints.apply_slippage_sell(price)
                self._log_trade(d, '卖出', pos.size, sell_price, reason_str)
                self.constraints.record_turnover(d._name, sell_amount, current_date)
                pending_sell_amounts += sell_amount
                self.close(d)

        # 1b. 减仓：仍在top_n但超配
        for d in self.datas:
            pos = self.getposition(d)
            if pos.size <= 0 or d._name not in selected_set:
                continue
            price = d.close[0]
            current_mv = pos.size * price
            if current_mv > max_single_mv * 1.05:
                excess_mv = current_mv - max_single_mv
                sell_shares = int(excess_mv / price / 100) * 100
                if sell_shares > 0:
                    sell_amount = sell_shares * price
                    ok, reason = self.constraints.can_sell(
                        d._name, price, sell_amount, pos.size, current_date,
                        current_positions=current_positions
                    )
                    if not ok:
                        continue
                    rank = code_rank.get(d._name, 0)
                    score = scores.get(d._name, 0)
                    reason_str = (f"多因子排名第{rank}/{total_n}，超配减仓"
                                  f"（当前{current_mv/total_value*100:.1f}%→目标{self.constraints.max_position_pct}%）")
                    sell_price = self.constraints.apply_slippage_sell(price)
                    self._log_trade(d, '卖出', sell_shares, sell_price, reason_str)
                    self.constraints.record_turnover(d._name, sell_amount, current_date)
                    pending_sell_amounts += sell_amount
                    self.sell(d, size=sell_shares, price=sell_price)

        # 1c. 风格分散减仓
        if self.constraints.max_per_sector > 0 and self.code_to_sector:
            sector_holdings = {}
            for d in self.datas:
                pos = self.getposition(d)
                if pos.size > 0:
                    sector = self.code_to_sector.get(d._name, '未知')
                    sector_holdings.setdefault(sector, []).append(
                        (d, scores.get(d._name, 0), pos.size * d.close[0])
                    )
            for sector, holdings in sector_holdings.items():
                if len(holdings) > self.constraints.max_per_sector:
                    holdings.sort(key=lambda x: x[1])
                    num_to_sell = len(holdings) - self.constraints.max_per_sector
                    for d, score, mv in holdings[:num_to_sell]:
                        pos = self.getposition(d)
                        price = d.close[0]
                        sell_amount = pos.size * price
                        ok, reason = self.constraints.can_sell(
                            d._name, price, sell_amount, pos.size, current_date,
                            current_positions=current_positions
                        )
                        if not ok:
                            continue
                        reason_str = f"{sector}风格超限减仓（综合得分{score:.2f}）"
                        sell_price = self.constraints.apply_slippage_sell(price)
                        self._log_trade(d, '卖出', pos.size, sell_price, reason_str)
                        self.constraints.record_turnover(d._name, sell_amount, current_date)
                        pending_sell_amounts += sell_amount
                        self.close(d)

        # 阶段2：现金感知买入
        effective_cash = self.broker.get_cash() + pending_sell_amounts

        for code in selected_codes:
            d = self.getdatabyname(code)
            if d is None:
                continue
            price = d.close[0]
            if price <= 0:
                continue
            pos = self.getposition(d)
            current_mv = pos.size * price
            buy_budget = max(0, max_single_mv - current_mv)
            buy_budget = min(buy_budget, effective_cash)
            if buy_budget <= 0:
                continue

            buy_price = self.constraints.apply_slippage_buy(price)
            target_size = int(buy_budget / buy_price / 100) * 100
            if target_size <= 0:
                continue
            buy_amount = target_size * buy_price

            current_positions = self._get_current_positions_mv()
            ok, reason = self.constraints.can_buy(
                code, buy_price, buy_amount, current_positions, total_value,
                current_date, effective_cash=effective_cash,
                code_to_sector=self.code_to_sector,
            )
            if not ok:
                continue
            ok_t, reason_t = self.constraints.check_turnover(
                buy_amount, total_value, current_date
            )
            if not ok_t:
                continue

            rank = code_rank.get(code, 0)
            score = scores.get(code, 0)
            raw = raw_factors.get(code, {})
            momentum_val = raw.get('momentum', 0)
            pe_val = raw.get('pe_pct', 0) or 0
            vol_val = raw.get('volatility', 0)
            reason_str = (f"多因子排名第{rank}/{total_n}，综合得分{score:.2f}，"
                          f"动量{momentum_val:.1f}%，PE百分位{pe_val:.0f}%，波动率{vol_val:.1f}%")
            self._log_trade(d, '买入', target_size, buy_price, reason_str)
            self.constraints.record_buy(code, current_date)
            self.constraints.record_turnover(code, buy_amount, current_date)
            self.buy(d, size=target_size, price=buy_price)
            effective_cash -= buy_amount


def run_backtest(data_dict, initial_capital=1000000, commission_rate=0.0003,
                 start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import run_backtest as _run
    return _run(MultiFactorStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)


def get_nav_curve(data_dict, initial_capital=1000000, commission_rate=0.0003,
                  start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import get_nav_curve as _nav
    return _nav(MultiFactorStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)
