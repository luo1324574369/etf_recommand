"""多因子轮动策略

动量 + 估值 + 低波动 三因子等权轮动。
复用 scoring.py 的因子计算和合成能力。
"""
import backtrader as bt
import pandas as pd
import numpy as np
from typing import Dict, Optional

from strategy.constraints import StrategyConstraints


def _multi_vote_decision(ma_sig: str, macd_sig: str, vol_sig: str) -> str:
    bull_count = 0
    if ma_sig == 'bull':
        bull_count += 1
    if macd_sig == 'bull':
        bull_count += 1
    if vol_sig == 'bull':
        bull_count += 1
    if bull_count >= 2:
        return 'bull'
    return 'bear'


def _compute_sector_momentum(data_dict, etf_to_sector, lookback):
    """计算赛道动量（赛道内ETF等权平均N日收益率）

    Args:
        data_dict: {code: DataFrame} 行情数据，需包含close列
        etf_to_sector: {code: sector} ETF到赛道的映射
        lookback: 回看天数

    Returns:
        {sector: momentum_pct} 各赛道动量（小数，如0.05表示5%）

    Raises:
        ValueError: 严格模式下，任一ETF数据不足lookback天时抛出
    """
    sector_returns = {}
    for code, sector in etf_to_sector.items():
        if code not in data_dict:
            continue
        df = data_dict[code]
        close = df['close'].values
        if len(close) <= lookback:
            raise ValueError(
                f"ETF {code} 数据不足{lookback}日，"
                f"无法计算赛道动量（严格模式）")
        roc = (close[-1] - close[-lookback - 1]) / close[-lookback - 1]
        sector_returns.setdefault(sector, []).append(roc)
    return {s: float(np.mean(rs)) for s, rs in sector_returns.items()}


def _apply_sector_penalty(scores, sector_momentum, etf_to_sector,
                         penalty_factor, exclude_threshold):
    """双轨制赛道惩罚：极端下跌硬排除，正常下跌软降权

    Args:
        scores: {code: score} ETF综合得分
        sector_momentum: {sector: momentum} 赛道动量
        etf_to_sector: {code: sector} ETF到赛道的映射
        penalty_factor: 软降权系数（0-1之间，越小惩罚越重）
        exclude_threshold: 硬排除阈值（如-0.10表示动量<-10%则排除）

    Returns:
        {code: penalized_score} 惩罚后的得分
    """
    penalized = {}
    for code, score in scores.items():
        sector = etf_to_sector.get(code)
        mom = sector_momentum.get(sector) if sector else None
        if mom is None:
            penalized[code] = score
        elif mom < exclude_threshold:
            penalized[code] = -np.inf
        elif mom < 0:
            penalized[code] = score * penalty_factor
        else:
            penalized[code] = score
    return penalized


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
        ('factor_weights', None),  # None=等权，或指定权重dict
        ('sector_penalty_factor', 0.7),       # 赛道软降权系数，1.0=关闭软降权
        ('sector_exclude_threshold', -0.10),   # 赛道硬排除阈值，-inf=关闭硬排除
        ('code_to_sector', None),  # ETF到赛道的映射 {code: sector}
        ('min_liquidity_amount', 50_000_000),  # 最低20日日均成交额（元），默认5000万
        ('drawdown_threshold', 15.0),   # 回撤止损触发阈值（%），默认15%
        ('drawdown_recovery', 5.0),     # 回撤恢复阈值（%），默认5%
        ('market_regime_switch', True),  # 是否启用市场状态切换
        ('benchmark_code', '510300'),    # 市场状态识别基准ETF代码
        ('regime_ma_period', 60),        # 市场状态判断均线周期
        ('enable_factor_monitor', True),  # 是否启用因子失效监控
        ('factor_monitor_lookback', 6),   # 因子监控回看期（月）
        ('factor_invalid_threshold', 0.0),# 因子失效阈值（IC均值<=此值视为失效）
        ('max_sector_exposure_pct', 50.0), # 行业仓位上限（%），0=不限制
        ('max_monthly_turnover', 30.0),    # 月度换手率上限（%），0=不限制
        ('core_allocation_pct', 50.0),     # 核心仓位占总资金比例(%)
        ('core_etf_codes', None),          # 核心仓位ETF代码列表/tuple，None时默认['510300','510500']
        ('core_weights', None),            # 核心仓位内部权重列表/tuple，None时等权
        ('regime_macd_fast', 12),          # MACD快线周期
        ('regime_macd_slow', 26),          # MACD慢线周期
        ('regime_macd_signal', 9),         # MACD信号线周期
        ('regime_vol_ma_period', 20),      # 成交额均线周期
        ('regime_vol_ratio_threshold', 1.2), # 成交额放大倍数阈值
        ('regime_confirm_days', 3),        # 连续确认天数
        ('bull_momentum_mult', 1.3),       # bull状态动量因子权重倍数
        ('bear_value_mult', 1.2),          # bear状态价值/红利/低波因子权重倍数
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
                'liquidity': bt.indicators.SumN(d.close * d.volume * 100, period=20) / 20,  # volume单位是手，*100转为股
            }
        if self.p.constraints is None:
            self.constraints = StrategyConstraints(
                max_sector_exposure_pct=self.p.max_sector_exposure_pct,
                max_monthly_turnover=self.p.max_monthly_turnover,
                core_allocation_pct=self.p.core_allocation_pct,
                core_etf_codes=self.p.core_etf_codes,
                core_weights=self.p.core_weights,
            )
        elif isinstance(self.p.constraints, dict):
            constraints_dict = dict(self.p.constraints)
            constraints_dict.setdefault('max_sector_exposure_pct', self.p.max_sector_exposure_pct)
            constraints_dict.setdefault('max_monthly_turnover', self.p.max_monthly_turnover)
            constraints_dict.setdefault('core_allocation_pct', self.p.core_allocation_pct)
            constraints_dict.setdefault('core_etf_codes', self.p.core_etf_codes)
            constraints_dict.setdefault('core_weights', self.p.core_weights)
            self.constraints = StrategyConstraints(**constraints_dict)
        else:
            self.constraints = self.p.constraints
            if not hasattr(self.constraints, 'max_sector_exposure_pct'):
                self.constraints.max_sector_exposure_pct = self.p.max_sector_exposure_pct
            if not hasattr(self.constraints, 'max_monthly_turnover'):
                self.constraints.max_monthly_turnover = self.p.max_monthly_turnover

        # code_to_sector默认为空，由外部设置
        self.code_to_sector = self.p.code_to_sector or {}

        self._drawdown_analyzer = bt.analyzers.DrawDown()
        self._drawdown_reduced = False

        # 换手率追踪：每个调仓周期累加买入金额
        self._turnover_records = []  # [{'date': str, 'buy_amount': float, 'total_value': float}]
        self._current_period_buys = 0.0  # 当前调仓周期累计买入金额
        self._current_period_date = None  # 当前调仓日

        # 市场状态识别
        self._regime_ma = {}
        if self.p.market_regime_switch:
            for d in self.datas:
                self._regime_ma[d] = bt.indicators.SimpleMovingAverage(d.close, period=self.p.regime_ma_period)
            benchmark_d = None
            for d in self.datas:
                if d._name == self.p.benchmark_code:
                    benchmark_d = d
                    break
            if benchmark_d is not None:
                self._benchmark_data = benchmark_d
                self._regime_macd_benchmark = bt.indicators.MACDHisto(
                    benchmark_d.close,
                    period_me1=self.p.regime_macd_fast,
                    period_me2=self.p.regime_macd_slow,
                    period_signal=self.p.regime_macd_signal,
                )
                benchmark_amount = benchmark_d.close * benchmark_d.volume * 100
                self._regime_vol_ma_benchmark = bt.indicators.SimpleMovingAverage(
                    benchmark_amount, period=self.p.regime_vol_ma_period
                )

        # 因子失效监控
        self._factor_history = {}  # {factor_name: [(date, factor_value, forward_return)]}
        self._invalid_factors = set()  # 当前失效的因子集合

        # 核心卫星策略状态变量
        self._core_positions = {}  # 核心持仓 {code: {'shares': int, 'avg_price': float}}
        self._core_built = False   # 核心仓位是否已建仓
        self._candidate_regime = 'bull'  # 候选市场状态（待确认）
        self._candidate_streak = 0       # 候选状态连续计数
        self._current_regime = 'bull'    # 已确认的当前市场状态
        if not hasattr(self, '_benchmark_data'):
            self._benchmark_data = None
        if not hasattr(self, '_regime_macd_benchmark'):
            self._regime_macd_benchmark = None
        if not hasattr(self, '_regime_vol_ma_benchmark'):
            self._regime_vol_ma_benchmark = None

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

    def _reduce_positions_to_half(self):
        for d in self.datas:
            if d._name in self._core_positions:
                continue
            pos = self.getposition(d)
            if pos.size > 0:
                sell_size = pos.size // 2
                if sell_size > 0:
                    price = d.close[0]
                    sell_price = self.constraints.apply_slippage_sell(price)
                    self._log_trade(d, '卖出', sell_size, sell_price,
                                   f"组合回撤止损，卫星仓位降仓50%（核心仓位不动）")
                    self.sell(d, size=sell_size, price=sell_price)

    def _check_drawdown_stoploss(self):
        dd_analysis = self._drawdown_analyzer.get_analysis()
        max_dd = float(dd_analysis.get('max', {}).get('drawdown', 0.0)) if dd_analysis else 0.0
        if max_dd > self.p.drawdown_threshold and not self._drawdown_reduced:
            self._reduce_positions_to_half()
            self._drawdown_reduced = True
        if max_dd < self.p.drawdown_recovery:
            self._drawdown_reduced = False

    def _find_data_by_name(self, code):
        for d in self.datas:
            if d._name == code:
                return d
        return None

    def _get_core_total_value(self):
        total = 0.0
        for code, pos in self._core_positions.items():
            data = self._find_data_by_name(code)
            if data is not None and data.close[0] is not None:
                total += pos['shares'] * data.close[0]
        return total

    def _get_satellite_total_value(self):
        core_codes = set(self._core_positions.keys())
        total = 0.0
        for d in self.datas:
            if d._name in core_codes:
                continue
            pos = self.getposition(d)
            if pos.size > 0 and d.close[0] is not None:
                total += pos.size * d.close[0]
        return total

    def _get_current_positions_mv(self, exclude_core=False):
        """获取当前持仓市值"""
        positions = {}
        core_codes = set(self._core_positions.keys()) if exclude_core else set()
        for d in self.datas:
            if exclude_core and d._name in core_codes:
                continue
            pos = self.getposition(d)
            if pos.size > 0:
                positions[d._name] = pos.size * d.close[0]
        return positions

    def _build_core_position(self):
        if self._core_built:
            return
        account_value = self.broker.getvalue()
        core_total = account_value * (self.p.core_allocation_pct / 100.0)
        codes = self.p.core_etf_codes or ["510300", "510500"]
        if self.p.core_weights is not None:
            weights = list(self.p.core_weights)
        else:
            n = len(codes)
            weights = [1.0 / n] * n
        for i, code in enumerate(codes):
            data = self._find_data_by_name(code)
            if data is not None and data.close[0] is not None and data.close[0] > 0:
                price = data.close[0]
                alloc = core_total * weights[i]
                shares = int((alloc * 0.9985) / (price * 100)) * 100
                if shares > 0:
                    self.buy(data=data, size=shares)
                    self._core_positions[code] = {'shares': shares, 'avg_price': price}
        self._core_built = True

    def _get_pe_percentile(self, code: str) -> Optional[float]:
        """获取ETF当前PE历史百分位（使用预加载缓存避免重复查库）"""
        if self.p.valuation_repo is None:
            return None
        # 使用预加载缓存
        if not hasattr(self, '_pe_cache'):
            self._pe_cache = {}
        if code in self._pe_cache:
            return self._pe_cache[code]
        try:
            pe_history = self.p.valuation_repo.get_pe_history(code)
            if not pe_history:
                self._pe_cache[code] = None
                return None
            current_pe = pe_history[-1].get('pe')
            if current_pe is None or current_pe <= 0:
                self._pe_cache[code] = None
                return None
            all_pes = [h['pe'] for h in pe_history if h.get('pe') and h['pe'] > 0]
            if not all_pes:
                self._pe_cache[code] = None
                return None
            rank = sum(1 for pe in all_pes if pe <= current_pe)
            result = rank / len(all_pes) * 100
            self._pe_cache[code] = result
            return result
        except Exception:
            self._pe_cache[code] = None
            return None

    def _get_dividend_yield(self, code: str) -> Optional[float]:
        if self.p.valuation_repo is None:
            return None
        if not hasattr(self, '_dy_cache'):
            self._dy_cache = {}
        if code in self._dy_cache:
            return self._dy_cache[code]
        try:
            latest_val = self.p.valuation_repo.get_latest_valuation(code)
            if not latest_val:
                self._dy_cache[code] = None
                return None
            dy = latest_val.get('dividend_yield')
            result = float(dy) if dy and dy > 0 else None
            self._dy_cache[code] = result
            return result
        except Exception:
            self._dy_cache[code] = None
            return None

    def _check_ma_signal(self) -> str:
        benchmark_d = self._benchmark_data
        if benchmark_d is None:
            benchmark_d = self._find_data_by_name(self.p.benchmark_code)
        if benchmark_d is None:
            return 'neutral'
        ma_value = self._regime_ma.get(benchmark_d)
        if ma_value is None or ma_value[0] is None:
            return 'neutral'
        if benchmark_d.close[0] is None:
            return 'neutral'
        if benchmark_d.close[0] > ma_value[0]:
            return 'bull'
        return 'bear'

    def _check_macd_signal(self) -> str:
        if self._regime_macd_benchmark is None:
            return 'neutral'
        histo = self._regime_macd_benchmark[0]
        if histo is None:
            return 'neutral'
        if histo > 0:
            return 'bull'
        return 'bear'

    def _check_volume_signal(self) -> str:
        if self._regime_vol_ma_benchmark is None:
            return 'neutral'
        vol_ma = self._regime_vol_ma_benchmark[0]
        if vol_ma is None:
            return 'neutral'
        benchmark_d = self._benchmark_data
        if benchmark_d is None:
            benchmark_d = self._find_data_by_name(self.p.benchmark_code)
        if benchmark_d is None or benchmark_d.close[0] is None or benchmark_d.volume[0] is None:
            return 'neutral'
        current_amount = benchmark_d.close[0] * benchmark_d.volume[0] * 100
        if vol_ma <= 0:
            return 'neutral'
        if current_amount / vol_ma >= self.p.regime_vol_ratio_threshold:
            return 'bull'
        return 'bear'

    def _get_market_regime(self):
        """识别当前市场状态（多指标投票制 + 3日确认）

        Returns:
            'bull' (主线行情): 多数指标看多且连续确认
            'bear' (震荡/弱势行情): 多数指标看空且连续确认
            'neutral': 未启用开关或指标仍在预热期
        """
        if not self.p.market_regime_switch:
            return 'neutral'

        ma_sig = self._check_ma_signal()
        macd_sig = self._check_macd_signal()
        vol_sig = self._check_volume_signal()

        if ma_sig == 'neutral' or macd_sig == 'neutral' or vol_sig == 'neutral':
            return self._current_regime

        candidate = _multi_vote_decision(ma_sig, macd_sig, vol_sig)

        if candidate == self._candidate_regime:
            self._candidate_streak += 1
        else:
            self._candidate_regime = candidate
            self._candidate_streak = 1

        if self._candidate_streak >= self.p.regime_confirm_days:
            self._current_regime = candidate

        return self._current_regime

    def _get_dynamic_factor_weights(self, available_factors):
        """根据市场状态返回动态因子权重

        主线行情（bull）: 侧重动量 -> 动量因子乘以 bull_momentum_mult，其他不变，归一化
        震荡/弱势行情（bear）: 侧重价值、红利、低波 -> 价值类因子乘以 bear_value_mult，其他不变，归一化
        neutral: 等权 base_weights，归一化
        """
        regime = self._get_market_regime()

        base_weights = {
            'momentum_60d': 0.33,
            'volatility_60d': 0.33,
            'pe_percentile': 0.34,
        }

        if 'dividend_yield' in available_factors:
            base_weights['dividend_yield'] = 0.25
            base_weights['momentum_60d'] = 0.25
            base_weights['volatility_60d'] = 0.25
            base_weights['pe_percentile'] = 0.25

        if regime == 'bull':
            new_weights = {}
            for f, w in base_weights.items():
                if 'momentum' in f:
                    new_weights[f] = w * self.p.bull_momentum_mult
                else:
                    new_weights[f] = w
            total = sum(new_weights.values())
            return {f: w / total for f, w in new_weights.items()}
        elif regime == 'bear':
            new_weights = {}
            value_keywords = ('pe_percentile', 'dividend_yield', 'volatility_60d')
            for f, w in base_weights.items():
                if any(k in f for k in value_keywords):
                    new_weights[f] = w * self.p.bear_value_mult
                else:
                    new_weights[f] = w
            total = sum(new_weights.values())
            return {f: w / total for f, w in new_weights.items()}
        else:
            total = sum(base_weights.values())
            return {f: w / total for f, w in base_weights.items()}

    def _update_factor_history(self, etf_factors):
        """更新因子历史数据，用于计算滚动IC"""
        if not self.p.enable_factor_monitor:
            return

        current_date = self.data.datetime.date(0)

        for code, factors in etf_factors.items():
            for factor_name, value in factors.items():
                if factor_name not in self._factor_history:
                    self._factor_history[factor_name] = []
                self._factor_history[factor_name].append((current_date, code, value))

    def _check_factor_validity(self, available_factors):
        """检查因子有效性（基于近N个月滚动IC）

        Returns:
            set: 当前有效的因子集合（剔除失效因子）
        """
        if not self.p.enable_factor_monitor:
            return set(available_factors)

        valid_factors = set()
        lookback_days = self.p.factor_monitor_lookback * 30
        threshold = self.p.factor_invalid_threshold

        for factor_name in available_factors:
            history = self._factor_history.get(factor_name, [])
            if len(history) < 10:
                valid_factors.add(factor_name)
                continue

            current_date = self.data.datetime.date(0)
            recent_data = [h for h in history if (current_date - h[0]).days <= lookback_days]

            if len(recent_data) < 5:
                valid_factors.add(factor_name)
                continue

            import numpy as np
            from scipy.stats import spearmanr

            values = [h[2] for h in recent_data]
            if len(set(values)) < 2:
                valid_factors.add(factor_name)
                continue

            factor_values = []
            forward_returns = []
            for i in range(len(recent_data) - 1):
                val = recent_data[i][2]
                next_val = recent_data[i + 1][2]
                if val != 0 and next_val != 0:
                    factor_values.append(val)
                    forward_returns.append(next_val / abs(val) - 1)

            if len(forward_returns) < 3:
                valid_factors.add(factor_name)
                continue

            corr, _ = spearmanr(factor_values, forward_returns)
            if not np.isnan(corr):
                from strategy.scoring import FACTOR_DIRECTIONS
                direction = FACTOR_DIRECTIONS.get(factor_name, 1)
                if (direction == 1 and corr > threshold) or (direction == -1 and corr < -threshold):
                    valid_factors.add(factor_name)
                else:
                    self._invalid_factors.add(factor_name)
            else:
                valid_factors.add(factor_name)

        return valid_factors

    def _compute_scores(self):
        """计算所有ETF的多因子综合得分"""
        etf_factors = {}
        etf_raw = {}
        for d in self.datas:
            code = d._name
            avg_amount = self.inds[d]['liquidity'][0]
            if avg_amount is not None and avg_amount < self.p.min_liquidity_amount:
                continue

            momentum = self.inds[d]['momentum'][0]
            volatility = self.inds[d]['volatility'][0]
            if momentum is None or volatility is None:
                continue

            pe_pct = self._get_pe_percentile(code)
            dy = self._get_dividend_yield(code)

            factors = {}
            factors['momentum_60d'] = float(momentum) if momentum is not None else None
            factors['volatility_60d'] = float(volatility) * 100 if volatility is not None else None
            if pe_pct is not None:
                factors['pe_percentile'] = pe_pct
            if dy is not None:
                factors['dividend_yield'] = dy

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
        from strategy.scoring import zscore_normalize, equal_weight_score, weighted_score

        # 确定可用因子（所有ETF都有的）
        available_factors = ['momentum_60d', 'volatility_60d']
        if all('pe_percentile' in f for f in etf_factors.values()):
            available_factors.append('pe_percentile')
        if all('dividend_yield' in f for f in etf_factors.values()):
            available_factors.append('dividend_yield')

        # 因子失效监控：剔除近6个月IC失效的因子
        self._update_factor_history(etf_factors)
        valid_factors = self._check_factor_validity(available_factors)
        if valid_factors != set(available_factors):
            available_factors = [f for f in available_factors if f in valid_factors]

        zscores = zscore_normalize(etf_factors, factor_names=available_factors)

        # 根据配置选择加权方式
        if self.p.factor_weights is not None:
            scores = weighted_score(zscores, self.p.factor_weights, factor_names=available_factors)
        elif self.p.market_regime_switch:
            dynamic_weights = self._get_dynamic_factor_weights(available_factors)
            scores = weighted_score(zscores, dynamic_weights, factor_names=available_factors)
        else:
            scores = equal_weight_score(zscores, factor_names=available_factors)

        # 赛道动量惩罚（双轨制）
        if self.code_to_sector and self.p.sector_penalty_factor is not None:
            # 收集当前可用的行情数据用于计算赛道动量
            current_data = {}
            for d in self.datas:
                code = d._name
                if code in scores:
                    # 获取最近 lookback_momentum + 1 天的收盘价
                    n = min(len(d), self.p.lookback_momentum + 1)
                    closes = [d.close[-i] for i in range(n)][::-1]
                    current_data[code] = pd.DataFrame({'close': closes})
            try:
                sector_mom = _compute_sector_momentum(
                    current_data, self.code_to_sector,
                    self.p.lookback_momentum
                )
                scores = _apply_sector_penalty(
                    scores, sector_mom, self.code_to_sector,
                    self.p.sector_penalty_factor,
                    self.p.sector_exclude_threshold
                )
            except ValueError:
                pass

        sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        selected = [code for code, score in sorted_codes[:self.p.top_n]]

        return selected, scores, etf_raw

    def next(self):
        if self.p.start_date:
            current_date = self.data.datetime.date(0)
            if current_date < self.p.start_date:
                return

        # 首日：建立核心仓位
        if not self._core_built:
            # 确保所有核心ETF的data.close[0]有值（非None非NaN），否则等下一bar
            codes = self.p.core_etf_codes or ["510300", "510500"]
            all_ready = True
            for code in codes:
                d = self._find_data_by_name(code)
                if d is None or d.close[0] is None or d.close[0] <= 0:
                    all_ready = False
                    break
            if all_ready:
                self._build_core_position()
                # 首日只建核心，跳过调仓，等下一个调仓周期
                # 在return之前设置_current_period_date，避免换手率追踪初始化问题
                if self._current_period_date is None:
                    current_date = self.data.datetime.date(0)
                    current_iso = current_date.isoformat()
                    self._current_period_date = current_iso
                return

        self._check_drawdown_stoploss()

        # 每日刷新市场状态（用于3日确认计数，即使非调仓日也要跑）
        if self.p.market_regime_switch:
            _ = self._get_market_regime()

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

        total_n = len(scores)
        code_rank = {code: i + 1 for i, (code, _) in enumerate(
            sorted(scores.items(), key=lambda x: x[1], reverse=True)
        )}

        current_date = self.data.datetime.date(0)
        account_total_value = self.broker.get_value()          # 账户总市值（参考用）
        satellite_total_value = self._get_satellite_total_value()  # 卫星市值（约束计算用，>0才用）
        constraint_base_value = satellite_total_value if satellite_total_value > 1e3 else account_total_value
        # 单仓上限 & 持仓市值按卫星计算
        max_single_mv = constraint_base_value * self.constraints.max_position_pct / 100
        current_positions = self._get_current_positions_mv(exclude_core=True)  # 只含卫星
        pending_sell_amounts = 0.0
        core_codes_set = set(self._core_positions.keys())
        # 过滤掉核心code：核心仓位永不参与轮动调仓
        selected_codes_filtered = [c for c in selected_codes if c not in core_codes_set]
        selected_set = set(selected_codes_filtered)

        # 阶段1：卖出
        # 1a. 清仓：不在新top_n的持仓
        for d in self.datas:
            # 核心仓位永不调仓
            if d._name in core_codes_set:
                continue
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
            # 核心仓位永不调仓
            if d._name in core_codes_set:
                continue
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
                                  f"（当前{current_mv/constraint_base_value*100:.1f}%→目标{self.constraints.max_position_pct}%）")
                    sell_price = self.constraints.apply_slippage_sell(price)
                    self._log_trade(d, '卖出', sell_shares, sell_price, reason_str)
                    self.constraints.record_turnover(d._name, sell_amount, current_date)
                    pending_sell_amounts += sell_amount
                    self.sell(d, size=sell_shares, price=sell_price)

        # 1c. 风格分散减仓
        if self.constraints.max_per_sector > 0 and self.code_to_sector:
            sector_holdings = {}
            for d in self.datas:
                # 核心仓位永不调仓
                if d._name in core_codes_set:
                    continue
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

        for code in selected_codes_filtered:  # 用过滤后的
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

            current_positions = self._get_current_positions_mv(exclude_core=True)
            ok, reason = self.constraints.can_buy(
                code, buy_price, buy_amount, current_positions, constraint_base_value,
                current_date, effective_cash=effective_cash,
                code_to_sector=self.code_to_sector,
            )
            if not ok:
                continue
            ok_t, reason_t = self.constraints.check_turnover(
                buy_amount, constraint_base_value, current_date,
                allow_first_build=len(current_positions) == 0
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
