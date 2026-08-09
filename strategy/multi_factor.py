"""多因子轮动策略

反转 + 估值 + 低波 + 红利 四因子 ICIR动态加权，核心卫星50/50隔离。
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
        ('core_allocation_pct', 50.0),     # 核心仓位占总资金比例(%) — neutral/baseline 目标占比
        ('core_dynamic', True),            # 是否启用动态核心（随市场状态小幅调整核心仓位占比）
        ('core_bull_alloc_pct', 55.0),     # bull状态核心目标占比(%) — 保守±5pp，避免追涨杀跌
        ('core_bear_alloc_pct', 45.0),     # bear状态核心目标占比(%)
        ('core_rebalance_threshold_pct', 3.0),  # 核心占比偏离>此值才再平衡(pp)
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

        # 回撤止损不使用独立的 DrawDown analyzer（需要cerebro注册才生效）
        # 改用策略自己计算的组合最高净值（backtrader next() bar级计算，更准确）
        self._portfolio_peak_value = 0.0
        self._drawdown_reduced = False
        # 防止优化器把阈值压到0导致频繁误触发：最低5%
        if self.p.drawdown_threshold < 5.0:
            self.p.drawdown_threshold = 5.0

        # 换手率追踪已移除：改由 backtest_utils._compute_trade_metrics_from_log 从 trade_list 派生

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
        self._factor_history = {}  # {factor_name: [(date, code, factor_value, close_price)]}
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

        # --- ICIR 加权/因子诊断状态 ---
        self._factor_ic_history = {}         # {factor: list of monthly IC values}
        self._factor_excluded_since = {}     # {factor: date}
        self._weight_history_rows = []       # [{date, factor1_w, factor2_w, ...}]
        self._ic_rolling_rows = []           # [{date, factor, ic}]
        self._regime_log = []                # [{date, regime, ma_sig, macd_sig, vol_sig, candidate, streak}]
        self.factor_diagnostics = None       # 回测结束后 set

        # --- 价格历史（用于调用 compute_all_factors，与IC预热保持一致）---
        self._price_history = {d._name: [] for d in self.datas}
        # 上一调仓日的因子快照（用于动态计算月度IC）
        self._last_month_factors = None

    def start(self):
        super().start()
        try:
            self._warmup_price_history()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"_warmup_price_history failed: {e}")
        try:
            self._warmup_ic_history()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"_warmup_ic_history failed: {e}")

    def _warmup_price_history(self):
        """从 backtrader 预加载数组填充 _price_history。

        backtrader 的 next() 在指标最小周期（如 StdDev(60)）之后才开始调用，
        导致前 N 个 bar 的价格未被 next() 中的 append 逻辑记录。
        此方法在 start() 中一次性预加载完整历史，确保首次调仓即可计算长周期因子。
        """
        import backtrader as bt
        for d in self.datas:
            code = d._name
            n = d.buflen()
            if n is None or n < 20:
                continue
            close_arr = d.close.array
            open_arr = d.open.array
            high_arr = d.high.array
            low_arr = d.low.array
            vol_arr = d.volume.array
            dt_arr = d.datetime.array
            prices = []
            for i in range(n):
                try:
                    c = float(close_arr[i])
                except (TypeError, ValueError, IndexError):
                    continue
                if c is None or np.isnan(c) or c <= 0:
                    continue
                try:
                    dt_val = dt_arr[i]
                    dt = bt.num2date(dt_val).date()
                except Exception:
                    continue
                try:
                    vol = float(vol_arr[i])
                    if np.isnan(vol):
                        vol = 0.0
                except (TypeError, ValueError):
                    vol = 0.0
                amount = c * vol * 100
                prices.append({
                    'trade_date': dt.isoformat(),
                    'open': float(open_arr[i]) if not np.isnan(float(open_arr[i])) else c,
                    'high': float(high_arr[i]) if not np.isnan(float(high_arr[i])) else c,
                    'low': float(low_arr[i]) if not np.isnan(float(low_arr[i])) else c,
                    'close': c,
                    'volume': vol,
                    'amount': amount,
                })
            if prices:
                self._price_history[code] = prices

    def _warmup_ic_history(self):
        """预热过去12个月的IC序列，用于ICIR加权

        遍历 self.datas 构建每个 ETF 的历史 prices，按月度截面切分，
        对每个截面计算因子值（winsorize+group_zscore）和下月收益，
        用 rank_ic_monthly 计算每个因子的月度IC序列。
        """
        import backtrader as bt
        from strategy.scoring import (
            compute_all_factors, winsorize_mad_3sigma, group_zscore,
            rank_ic_monthly, FACTOR_DIRECTIONS,
        )
        from config.settings import ETF_UNIVERSE

        code_to_sector = {e['code']: e.get('sector', '其他') for e in ETF_UNIVERSE}

        # 收集每个 ETF 的历史价格序列（从 backtrader 预加载数组读取）
        code_prices = {}  # {code: list of price dicts (升序)}
        for d in self.datas:
            code = d._name
            n = d.buflen()
            if n is None or n < 60:
                continue
            close_arr = d.close.array
            open_arr = d.open.array
            high_arr = d.high.array
            low_arr = d.low.array
            vol_arr = d.volume.array
            dt_arr = d.datetime.array
            prices = []
            for i in range(n):
                try:
                    c = float(close_arr[i])
                except (TypeError, ValueError, IndexError):
                    continue
                if c is None or np.isnan(c) or c <= 0:
                    continue
                try:
                    dt_val = dt_arr[i]
                    dt = bt.num2date(dt_val).date()
                except Exception:
                    continue
                def _safe_float(v, default=c):
                    try:
                        fv = float(v)
                        if np.isnan(fv):
                            return default
                        return fv
                    except (TypeError, ValueError):
                        return default
                prices.append({
                    'trade_date': dt.isoformat(),
                    'open': _safe_float(open_arr[i]),
                    'high': _safe_float(high_arr[i]),
                    'low': _safe_float(low_arr[i]),
                    'close': c,
                    'volume': _safe_float(vol_arr[i], 0.0),
                })
            if len(prices) >= 60:
                code_prices[code] = prices

        if len(code_prices) < 3:
            return

        # 取 warmup 截止日 = start_date
        warmup_end = self.p.start_date
        if warmup_end is None:
            all_dates = []
            for prices in code_prices.values():
                all_dates.extend(p['trade_date'] for p in prices)
            if not all_dates:
                return
            warmup_end_str = max(all_dates)
        else:
            warmup_end_str = warmup_end.isoformat() if hasattr(warmup_end, 'isoformat') else str(warmup_end)

        # 过滤 warmup_end 之前的 prices
        for code in list(code_prices.keys()):
            code_prices[code] = [p for p in code_prices[code] if p['trade_date'] <= warmup_end_str]
            if len(code_prices[code]) < 60:
                del code_prices[code]

        if len(code_prices) < 3:
            return

        # 收集所有日期，找出每月最后一个交易日
        all_dates_set = set()
        for prices in code_prices.values():
            for p in prices:
                all_dates_set.add(p['trade_date'])
        all_dates_sorted = sorted(all_dates_set)

        monthly_last_dates = []
        last_ym = None
        last_date = None
        for d_str in all_dates_sorted:
            ym = d_str[:7]
            if last_ym is None:
                last_ym = ym
                last_date = d_str
            elif ym == last_ym:
                last_date = d_str
            else:
                monthly_last_dates.append(last_date)
                last_ym = ym
                last_date = d_str
        if last_date:
            monthly_last_dates.append(last_date)

        # 取最近13个月末（多1个用于计算forward return）
        monthly_last_dates = monthly_last_dates[-13:]
        if len(monthly_last_dates) < 4:
            return

        # 对每个截面日计算因子值 + 下月收益
        factor_ic = {}

        for i in range(len(monthly_last_dates) - 1):
            cut_date_str = monthly_last_dates[i]
            next_date_str = monthly_last_dates[i + 1]

            etf_factor_values = {}  # {factor: {code: value}}
            etf_returns = {}        # {code: next_month_return}
            codes_with_data = []

            for code, prices in code_prices.items():
                cut_idx = None
                next_idx = None
                for j, p in enumerate(prices):
                    if p['trade_date'] == cut_date_str:
                        cut_idx = j
                    if p['trade_date'] == next_date_str:
                        next_idx = j
                    if cut_idx is not None and next_idx is not None:
                        break

                if cut_idx is None or cut_idx < 30:
                    continue
                if next_idx is None or next_idx <= cut_idx:
                    continue

                cut_prices = prices[:cut_idx + 1]
                cut_close = cut_prices[-1]['close']
                next_close = prices[next_idx]['close']
                if cut_close <= 0:
                    continue
                etf_returns[code] = (next_close / cut_close - 1)

                pe_pct = None
                dy_val = None
                if self.p.valuation_repo is not None:
                    try:
                        pe_pct = self.p.valuation_repo.get_pe_percentile(code, end_date=cut_date_str)
                    except Exception:
                        try:
                            pe_pct = self.p.valuation_repo.get_pe_percentile(code)
                        except Exception:
                            pe_pct = None
                    # 获取截止日的股息率（避免lookahead bias）
                    try:
                        valuations = self.p.valuation_repo.get_valuation(code, end_date=cut_date_str)
                        if valuations:
                            dy = valuations[0].get('dividend_yield')
                            dy_val = float(dy) if dy and dy > 0 else None
                    except Exception:
                        dy_val = None

                factors = compute_all_factors(code, cut_prices, pe_percentile=pe_pct, dividend_yield=dy_val)
                if not factors:
                    continue

                for f, v in factors.items():
                    etf_factor_values.setdefault(f, {})[code] = v
                codes_with_data.append(code)

            if len(codes_with_data) < 3:
                continue

            codes = codes_with_data
            for factor, vals in etf_factor_values.items():
                if factor not in FACTOR_DIRECTIONS:
                    continue
                valid_codes = [c for c in codes if c in vals and vals[c] is not None]
                if len(valid_codes) < 3:
                    continue

                s = pd.Series({c: vals[c] for c in valid_codes})
                s = winsorize_mad_3sigma(s)
                zscores = group_zscore(valid_codes, {c: s[c] for c in valid_codes}, code_to_sector)

                factor_series = pd.Series({c: zscores.get(c, 0.0) for c in valid_codes})
                return_series = pd.Series({c: etf_returns.get(c, np.nan) for c in valid_codes})
                ic = rank_ic_monthly(factor_series, return_series)
                factor_ic.setdefault(factor, []).append(ic)

        # 保存到 state（过滤掉全 None 的因子）
        self._factor_ic_history = {
            f: [v for v in vs if v is not None]
            for f, vs in factor_ic.items()
            if vs and any(v is not None for v in vs)
        }

    def _compute_icir_factor_weights(self):
        """调仓日调用，返回 (weights, excluded, mode)"""
        if not self._factor_ic_history:
            from strategy.scoring import FACTOR_DIRECTIONS
            factors = list(FACTOR_DIRECTIONS.keys())
            return {f: 1.0 / len(factors) for f in factors}, {}, 'equal_weight_fallback'
        from strategy.scoring import compute_icir_weights
        hist = {k: list(v) for k, v in self._factor_ic_history.items()}
        return compute_icir_weights(hist, rolling_months=12, return_mode=True)

    def _log_trade(self, d, direction, size, price, reason, trade_type='satellite'):
        """记录交易日志

        Args:
            trade_type: 'core' (核心建仓) | 'satellite' (卫星轮动) | 'stoploss' (回撤止损)
        """
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
        cash_after = self.broker.get_cash()
        total_value = self.broker.getvalue()
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
            'trade_type': trade_type,
            'total_value': total_value,
        })

    def _reduce_positions_to_half(self):
        for d in self.datas:
            if d._name in self._core_positions:
                continue
            pos = self.getposition(d)
            if pos.size > 0:
                # A股卖单必须是100股整数倍：pos.size→half→对齐100
                half_size = pos.size // 2
                sell_size = (half_size // 100) * 100
                if sell_size > 0:
                    price = d.close[0]
                    sell_price = self.constraints.apply_slippage_sell(price)
                    self._log_trade(d, '卖出', sell_size, sell_price,
                                   f"组合回撤止损，卫星仓位降仓50%（核心仓位不动）",
                                   trade_type='stoploss')
                    self.sell(d, size=sell_size, price=sell_price)

    def _check_drawdown_stoploss(self):
        """回撤止损（策略自算，避免依赖cerebro未注册的analyzer）"""
        current_value = self.broker.getvalue()
        if current_value > self._portfolio_peak_value:
            self._portfolio_peak_value = current_value
        if self._portfolio_peak_value <= 0:
            return
        drawdown_pct = (1 - current_value / self._portfolio_peak_value) * 100
        if drawdown_pct > self.p.drawdown_threshold and not self._drawdown_reduced:
            self._reduce_positions_to_half()
            self._drawdown_reduced = True
        if drawdown_pct < self.p.drawdown_recovery:
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
        # 首日用动态目标占比（基于 regime 初始值）而非固定 50%
        target_pct = self._get_target_core_alloc()
        core_total = account_value * (target_pct / 100.0)
        codes = self.p.core_etf_codes or ["510300", "510500"]
        if self.p.core_weights is not None:
            weights = list(self.p.core_weights)
        else:
            n = len(codes)
            weights = [1.0 / n] * n
        for i, code in enumerate(codes):
            data = self._find_data_by_name(code)
            if data is not None and data.close[0] is not None and data.close[0] > 0:
                close_price = data.close[0]
                # 应用滑点（与卫星买入一致）
                buy_price = self.constraints.apply_slippage_buy(close_price)
                alloc = core_total * weights[i]
                shares = int((alloc * 0.9985) / (buy_price * 100)) * 100
                if shares > 0:
                    self._log_trade(data, '买入', shares, buy_price,
                                   f"核心仓位建仓（动态目标{target_pct:.0f}%，内部权重{weights[i]*100:.0f}%）",
                                   trade_type='core')
                    self.buy(data=data, size=shares, price=buy_price)
                    self._core_positions[code] = {'shares': shares, 'avg_price': buy_price}
        self._core_built = True

    def _get_target_core_alloc(self) -> float:
        """根据已确认的市场状态返回核心仓位目标占比(%)。

        【关键】直接读 self._current_regime，不调用 _get_market_regime()（有streak++副作用），
        避免同一天streak被double-count导致regime提前切换确认。

        档位保守（±5pp）：bull=55%, bear=45%, neutral=50%
        — 避免regime滞后信号造成追涨杀跌（9月底指数高点加、10月暴跌后减）
        """
        if not self.p.core_dynamic:
            return self.p.core_allocation_pct
        # 直接读取已确认状态（无副作用）。_current_regime 初始='bull'兼容首日建仓
        regime = self._current_regime if hasattr(self, '_current_regime') else 'neutral'
        if regime == 'bull':
            return self.p.core_bull_alloc_pct
        elif regime == 'bear':
            return self.p.core_bear_alloc_pct
        else:
            return self.p.core_allocation_pct

    def _rebalance_core_position(self):
        """调仓日再平衡核心仓位到目标占比。

        仅当实际占比偏离目标占比超过 core_rebalance_threshold_pct (默认5pp) 时才执行，
        避免 regime 频繁切换造成的交易成本。
        买入/卖出按 core_weights 比例在各核心 ETF 间分配。
        """
        if not self._core_built:
            return
        account_value = self.broker.getvalue()
        if account_value <= 0:
            return
        core_mv = self._get_core_total_value()
        actual_pct = core_mv / account_value * 100.0
        target_pct = self._get_target_core_alloc()
        gap = target_pct - actual_pct  # 正值=需加仓核心，负值=需减仓核心
        threshold = self.p.core_rebalance_threshold_pct
        if abs(gap) <= threshold:
            return
        # 每个核心 ETF 需要调整的金额
        codes = self.p.core_etf_codes or ["510300", "510500"]
        weights = list(self.p.core_weights) if self.p.core_weights is not None else [1.0 / len(codes)] * len(codes)
        # 目标核心总资金
        target_core_mv = account_value * (target_pct / 100.0)
        for i, code in enumerate(codes):
            d = self._find_data_by_name(code)
            if d is None or d.close[0] is None or d.close[0] <= 0:
                continue
            target_code_mv = target_core_mv * weights[i]
            current_mv = 0.0
            if code in self._core_positions:
                current_mv = self._core_positions[code]['shares'] * d.close[0]
            diff_mv = target_code_mv - current_mv
            close_price = d.close[0]
            if diff_mv > 0:  # 加仓
                buy_price = self.constraints.apply_slippage_buy(close_price)
                # 留0.15%现金避免现金不足
                shares = int((diff_mv * 0.9985) / (buy_price * 100)) * 100
                if shares > 0:
                    self._log_trade(d, '买入', shares, buy_price,
                                   f"核心仓位加仓（目标{target_pct:.0f}%，偏离{gap:+.1f}pp，调仓差额{diff_mv:,.0f}）",
                                   trade_type='core_rebalance')
                    self.buy(data=d, size=shares, price=buy_price)
                    old_shares = self._core_positions.get(code, {}).get('shares', 0)
                    old_avg = self._core_positions.get(code, {}).get('avg_price', buy_price)
                    new_shares = old_shares + shares
                    new_avg = (old_avg * old_shares + buy_price * shares) / new_shares if new_shares > 0 else buy_price
                    self._core_positions[code] = {'shares': new_shares, 'avg_price': new_avg}
            elif diff_mv < 0:  # 减仓
                sell_price = self.constraints.apply_slippage_sell(close_price)
                shares_to_sell = int(abs(diff_mv) / (sell_price * 100)) * 100
                if shares_to_sell > 0 and code in self._core_positions:
                    current_shares = self._core_positions[code]['shares']
                    shares_to_sell = min(shares_to_sell, current_shares)
                    if shares_to_sell > 0:
                        shares_to_sell = (shares_to_sell // 100) * 100
                        if shares_to_sell <= 0:
                            continue
                        self._log_trade(d, '卖出', shares_to_sell, sell_price,
                                       f"核心仓位减仓（目标{target_pct:.0f}%，偏离{gap:+.1f}pp，调仓差额{diff_mv:,.0f}）",
                                       trade_type='core_rebalance')
                        self.sell(data=d, size=shares_to_sell, price=sell_price)
                        self._core_positions[code]['shares'] = current_shares - shares_to_sell

    def _get_pe_percentile(self, code: str, current_date_str: str = None) -> Optional[float]:
        """获取ETF在指定日期的PE历史百分位（严格过滤 future data）

        Args:
            code: ETF代码
            current_date_str: 当前交易日字符串（YYYY-MM-DD），仅使用 <= 此日期的PE历史
        """
        if self.p.valuation_repo is None:
            return None
        try:
            pe_history = self.p.valuation_repo.get_pe_history(code, end_date=current_date_str)
            if not pe_history:
                return None
            current_pe = pe_history[-1].get('pe')
            if current_pe is None or current_pe <= 0:
                return None
            all_pes = [h['pe'] for h in pe_history if h.get('pe') and h['pe'] > 0]
            if not all_pes:
                return None
            rank = sum(1 for pe in all_pes if pe <= current_pe)
            result = rank / len(all_pes) * 100
            return result
        except Exception:
            return None

    def _get_dividend_yield(self, code: str, current_date_str: str = None) -> Optional[float]:
        """获取ETF在指定日期的股息率（严格过滤 future data）

        Args:
            code: ETF代码
            current_date_str: 当前交易日字符串（YYYY-MM-DD），取 <= 此日期的最新一条估值记录
        """
        if self.p.valuation_repo is None:
            return None
        try:
            valuations = self.p.valuation_repo.get_valuation(code, end_date=current_date_str)
            if not valuations:
                return None
            latest_val = valuations[0]  # get_valuation 返回按 trade_date DESC 排序
            dy = latest_val.get('dividend_yield')
            result = float(dy) if dy and dy > 0 else None
            return result
        except Exception:
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

        主线行情（bull）: 侧重动量 -> momentum_120d因子乘以 bull_momentum_mult，其他不变，归一化
        震荡/弱势行情（bear）: 侧重价值、红利 -> pe_percentile和dividend_yield乘以 bear_value_mult，其他不变，归一化
        neutral: 等权 base_weights，归一化
        """
        regime = self._get_market_regime()

        # 等权基准权重（仅包含可用因子）
        n = len(available_factors) if available_factors else 1
        base_weights = {f: 1.0 / n for f in available_factors}

        if regime == 'bull':
            new_weights = {}
            for f, w in base_weights.items():
                if 'momentum_120d' in f:
                    new_weights[f] = w * self.p.bull_momentum_mult
                else:
                    new_weights[f] = w
            total = sum(new_weights.values())
            if total > 0:
                return {f: w / total for f, w in new_weights.items()}
            return base_weights
        elif regime == 'bear':
            new_weights = {}
            value_keywords = ('pe_percentile', 'dividend_yield')
            for f, w in base_weights.items():
                if any(k in f for k in value_keywords):
                    new_weights[f] = w * self.p.bear_value_mult
                else:
                    new_weights[f] = w
            total = sum(new_weights.values())
            if total > 0:
                return {f: w / total for f, w in new_weights.items()}
            return base_weights
        else:
            return base_weights

    def _update_factor_history(self, etf_factors):
        """更新因子历史数据，用于计算滚动IC

        存储格式: {factor_name: [(date, code, factor_value, close_price), ...]}
        close_price 用于计算真实前向收益率，避免使用因子值比值作为伪收益率。
        """
        if not self.p.enable_factor_monitor:
            return

        current_date = self.data.datetime.date(0)

        for code, factors in etf_factors.items():
            # 获取当前收盘价（优先从价格历史取，回退到数据源）
            close_price = None
            if code in self._price_history and self._price_history[code]:
                close_price = self._price_history[code][-1]['close']
            else:
                d = self._find_data_by_name(code)
                if d is not None and d.close[0] is not None:
                    close_price = float(d.close[0])

            for factor_name, value in factors.items():
                if factor_name not in self._factor_history:
                    self._factor_history[factor_name] = []
                self._factor_history[factor_name].append((current_date, code, value, close_price))

    def _check_factor_validity(self, available_factors):
        """检查因子有效性（基于近N个月滚动IC，使用真实价格前向收益）

        对每个调仓截面日，计算截面因子值与下一截面日前向收益的Spearman秩相关，
        若近 factor_monitor_lookback 个月内平均IC（方向调整后）<= threshold，则判定失效。

        Returns:
            set: 当前有效的因子集合（剔除失效因子）
        """
        if not self.p.enable_factor_monitor:
            return set(available_factors)

        from scipy.stats import spearmanr
        from strategy.scoring import FACTOR_DIRECTIONS

        valid_factors = set()
        lookback_days = self.p.factor_monitor_lookback * 30
        threshold = self.p.factor_invalid_threshold
        current_date = self.data.datetime.date(0)

        for factor_name in available_factors:
            history = self._factor_history.get(factor_name, [])
            if len(history) < 10:
                valid_factors.add(factor_name)
                continue

            # 过滤到 lookback 窗口内
            recent_data = [h for h in history if (current_date - h[0]).days <= lookback_days]
            if len(recent_data) < 5:
                valid_factors.add(factor_name)
                continue

            # 按日期分组: {date: {code: (factor_value, close_price)}}
            by_date = {}
            for entry in recent_data:
                date, code, value, close_price = entry
                by_date.setdefault(date, {})[code] = (value, close_price)

            sorted_dates = sorted(by_date.keys())
            if len(sorted_dates) < 2:
                valid_factors.add(factor_name)
                continue

            # 对每对相邻截面日计算IC：因子值 vs 前向收益
            ic_values = []
            for i in range(len(sorted_dates) - 1):
                date_i = sorted_dates[i]
                date_j = sorted_dates[i + 1]
                data_i = by_date[date_i]
                data_j = by_date[date_j]

                # 取两个截面共有的ETF
                common_codes = [c for c in data_i if c in data_j]
                if len(common_codes) < 3:
                    continue

                factor_vals = []
                forward_rets = []
                for c in common_codes:
                    val_i, close_i = data_i[c]
                    _, close_j = data_j[c]
                    if val_i is None or close_i is None or close_j is None or close_i <= 0:
                        continue
                    factor_vals.append(float(val_i))
                    forward_rets.append(float(close_j / close_i - 1))

                if len(factor_vals) < 3:
                    continue
                if len(set(factor_vals)) < 2 or len(set(forward_rets)) < 2:
                    continue

                corr, _ = spearmanr(factor_vals, forward_rets)
                if not np.isnan(corr):
                    ic_values.append(corr)

            if len(ic_values) < 3:
                valid_factors.add(factor_name)
                continue

            avg_ic = float(np.mean(ic_values))
            direction = FACTOR_DIRECTIONS.get(factor_name, 1)
            # 方向调整后IC > threshold 才视为有效
            effective_ic = avg_ic * direction
            if effective_ic > threshold:
                valid_factors.add(factor_name)
                # 自动恢复：因子IC回升则从失效集合中移除
                self._invalid_factors.discard(factor_name)
            else:
                self._invalid_factors.add(factor_name)

        return valid_factors

    def _compute_scores(self):
        """计算所有ETF的多因子综合得分

        统一使用 scoring.compute_all_factors 计算因子值，确保IC预热与实盘因子一致。
        bt.indicators 仅保留用于流动性过滤和交易日志展示，不参与因子打分。
        """
        from strategy.scoring import (
            compute_all_factors, zscore_normalize, equal_weight_score,
            weighted_score, rank_ic_monthly,
        )
        from collections import deque

        etf_factors = {}
        etf_raw = {}
        current_date_str = self.data.datetime.date(0).isoformat()

        for d in self.datas:
            code = d._name
            # 流动性过滤仍使用 bt.indicators（非因子打分）
            avg_amount = self.inds[d]['liquidity'][0]
            if avg_amount is not None and avg_amount < self.p.min_liquidity_amount:
                continue

            # 从价格历史获取 prices 列表（与IC预热使用相同数据源）
            prices_list = self._price_history.get(code, [])
            if len(prices_list) < 20:
                continue

            # 严格过滤 future data：PE百分位和股息率仅使用 <= 当前日期的数据
            pe_pct = self._get_pe_percentile(code, current_date_str)
            dy = self._get_dividend_yield(code, current_date_str)

            # 统一因子计算：调用 compute_all_factors
            factors = compute_all_factors(
                code, prices_list, end_date=current_date_str,
                pe_percentile=pe_pct, dividend_yield=dy,
            )
            if not factors:
                continue

            # 至少需要 reversal_20d 和 volatility_60d
            if factors.get('reversal_20d') is None or factors.get('volatility_60d') is None:
                continue

            etf_factors[code] = factors
            etf_raw[code] = factors

        # ===== B1 NEW: 横截面动量 追加到 etf_factors =====
        # 在33只ETF池子里按收益率排名→百分位,IC是时序动量的3-5倍
        from strategy.scoring import cross_sectional_momentum as _cs_mom
        _periods = [120]
        _cross_ret = {}
        for _d in self.datas:
            _c = _d._name
            if _c not in etf_factors:
                continue   # 已被流动性/最小长度过滤,不参与横截面
            _prices = self._price_history.get(_c, [])
            if len(_prices) < 121:
                continue
            _row = {}
            for _p in _periods:
                if len(_prices) < _p + 1:
                    continue
                try:
                    _denom = _prices[-_p - 1]['close']
                    if _denom and _denom > 0:
                        _row[_p] = float((_prices[-1]['close'] - _denom) / _denom)
                except (ZeroDivisionError, IndexError, TypeError):
                    pass
            if _row:
                _cross_ret[_c] = _row
        if _cross_ret:
            _cf = _cs_mom(_cross_ret, _periods)
            for _c, _fs in _cf.items():
                if _c in etf_factors:
                    etf_factors[_c].update(_fs)
        # =====================================================

        if not etf_factors:
            # 即使没有可用ETF，也保存因子快照供下月IC计算
            self._last_month_factors = None
            return [], {}, {}

        # 确定可用因子（多数ETF有即可纳入；zscore_normalize 对缺失值返回0，不影响排名稳健性）
        # 原bug: 用 all() 要求所有ETF都有该因子，商品ETF(159985/518880)缺PE导致pe_percentile被永久剔除
        available_factors = ['reversal_20d', 'volatility_60d']
        n_etfs = len(etf_factors)
        min_count = max(3, n_etfs // 2)  # 至少半数ETF有该因子
        if sum(1 for f in etf_factors.values() if 'momentum_120d' in f) >= min_count:
            available_factors.append('momentum_120d')
        if sum(1 for f in etf_factors.values() if 'pe_percentile' in f) >= min_count:
            available_factors.append('pe_percentile')
        if sum(1 for f in etf_factors.values() if 'dividend_yield' in f) >= min_count:
            available_factors.append('dividend_yield')
        # B1: 横截面120日动量
        if sum(1 for f in etf_factors.values() if 'cross_mom_120d' in f) >= min_count:
            available_factors.append('cross_mom_120d')

        # --- C3+C4: 动态更新IC历史 + 滚动IC记录 ---
        # 用上一调仓日因子快照 vs 当前收益计算月度IC
        if self._last_month_factors:
            current_returns = {}
            for code in self._last_month_factors:
                if code in self._price_history and len(self._price_history[code]) >= 2:
                    old_close = self._last_month_factors[code].get('_close')
                    curr_close = self._price_history[code][-1]['close']
                    if old_close and old_close > 0:
                        current_returns[code] = (curr_close / old_close - 1)

            if len(current_returns) >= 3:
                codes_ic = list(current_returns.keys())
                # 仅遍历上月因子快照中的打分因子（排除 _close 等元数据和非打分因子如 avg_amount_20d）
                snapshot_factors = [
                    fn for fn in self._last_month_factors[codes_ic[0]]
                    if fn != '_close' and fn in available_factors
                ]
                for fn in snapshot_factors:
                    f_series = pd.Series({c: self._last_month_factors[c].get(fn, np.nan) for c in codes_ic})
                    r_series = pd.Series({c: current_returns[c] for c in codes_ic})
                    ic = rank_ic_monthly(f_series, r_series)
                    if ic is not None:
                        dq = self._factor_ic_history.setdefault(fn, deque(maxlen=24))
                        dq.append(ic)
                        self._ic_rolling_rows.append({
                            'date': current_date_str,
                            'factor': fn,
                            'ic': ic,
                        })

        # 保存当前因子快照供下月IC计算
        self._last_month_factors = {code: dict(factors) for code, factors in etf_factors.items()}
        for code in etf_factors:
            if code in self._price_history and self._price_history[code]:
                self._last_month_factors[code]['_close'] = self._price_history[code][-1]['close']

        # 因子失效监控：剔除近6个月IC失效的因子
        self._update_factor_history(etf_factors)
        valid_factors = self._check_factor_validity(available_factors)
        if valid_factors != set(available_factors):
            available_factors = [f for f in available_factors if f in valid_factors]

        # 保底机制：即使所有因子都被判失效，也至少保留 reversal_20d 和 volatility_60d
        # 避免排名0/0清仓踩踏（Bug #1/#3 根因）
        if not available_factors:
            available_factors = ['reversal_20d', 'volatility_60d']

        zscores = zscore_normalize(etf_factors, factor_names=available_factors)

        # ICIR 加权（主路径）
        icir_weights, icir_excluded, icir_mode = self._compute_icir_factor_weights()
        effective_weights = {f: icir_weights.get(f, 0.0) for f in available_factors}
        total_w = sum(effective_weights.values())

        current_date = self.data.datetime.date(0)
        if total_w > 1e-9:
            # Regime-aware 二次叠加：ICIR权重 × 牛熊倍数 → 归一化
            if self.p.market_regime_switch:
                regime = self._get_market_regime()
                adjusted = dict(effective_weights)
                if regime == 'bull':
                    for f in adjusted:
                        # 时序动量 + 横截面动量 都在牛市享受1.3x加成
                        if 'momentum_120d' in f or 'cross_mom_' in f:
                            adjusted[f] *= self.p.bull_momentum_mult
                elif regime == 'bear':
                    value_keys = ('pe_percentile', 'dividend_yield', 'volatility')
                    for f in adjusted:
                        if any(k in f for k in value_keys):
                            adjusted[f] *= self.p.bear_value_mult
                t = sum(adjusted.values())
                if t > 0:
                    effective_weights = {f: w / t for f, w in adjusted.items()}
                    weights_used_mode = f'{icir_mode}_x_regime_{regime}'
                else:
                    weights_used_mode = icir_mode
            else:
                weights_used_mode = icir_mode
            scores = weighted_score(zscores, effective_weights, factor_names=available_factors)
            weights_used = effective_weights
        else:
            # Fallback: 原始加权逻辑
            if self.p.factor_weights is not None:
                scores = weighted_score(zscores, self.p.factor_weights, factor_names=available_factors)
                weights_used = dict(self.p.factor_weights)
                weights_used_mode = 'param_factor_weights'
            elif self.p.market_regime_switch:
                dynamic_weights = self._get_dynamic_factor_weights(available_factors)
                scores = weighted_score(zscores, dynamic_weights, factor_names=available_factors)
                weights_used = dynamic_weights
                weights_used_mode = 'regime_dynamic'
            else:
                scores = equal_weight_score(zscores, factor_names=available_factors)
                weights_used = {f: 1.0 / len(available_factors) for f in available_factors} if available_factors else {}
                weights_used_mode = 'equal_weight'

        # 记录权重历史
        row = {'date': current_date.isoformat()}
        row.update({f: float(weights_used.get(f, 0.0)) for f in available_factors})
        self._weight_history_rows.append(row)

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
        # 维护价格历史（用于调用 compute_all_factors，确保与IC预热使用相同因子计算逻辑）
        # start() 已预加载完整历史，这里只追加新 bar（通过日期去重避免重复）
        for d in self.datas:
            code = d._name
            if d.close[0] is None or np.isnan(d.close[0]) or d.close[0] <= 0:
                continue
            try:
                date_str = d.datetime.date(0).isoformat()
            except Exception:
                continue
            hist = self._price_history.get(code, [])
            if hist and hist[-1].get('trade_date') == date_str:
                continue
            amount = getattr(d, 'amount', [0])[0] if hasattr(d, 'amount') else d.volume[0] * d.close[0]
            hist.append({
                'trade_date': date_str,
                'open': float(d.open[0]),
                'high': float(d.high[0]),
                'low': float(d.low[0]),
                'close': float(d.close[0]),
                'volume': float(d.volume[0]),
                'amount': float(amount),
            })

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
                return

        self._check_drawdown_stoploss()

        # 每日刷新市场状态（用于3日确认计数，即使非调仓日也要跑）
        if self.p.market_regime_switch:
            _ = self._get_market_regime()

        # 每日再平衡核心仓位（不等待调仓日），减少regime信号与20天调仓窗的时间错位
        # — 用当前已确认的_current_regime判定档位（±5pp），温和调整避免追涨杀跌
        self._rebalance_core_position()

        self.day_count += 1
        if self.day_count % self.p.rebalance_freq != 0:
            return

        # 调仓日记录 regime 快照（用于诊断）
        if self.p.market_regime_switch:
            ma_sig = self._check_ma_signal()
            macd_sig = self._check_macd_signal()
            vol_sig = self._check_volume_signal()
            self._regime_log.append({
                'date': self.data.datetime.date(0).isoformat(),
                'regime': self._current_regime,
                'candidate': self._candidate_regime,
                'streak': self._candidate_streak,
                'ma_sig': ma_sig,
                'macd_sig': macd_sig,
                'vol_sig': vol_sig,
            })

        selected_codes, scores, raw_factors = self._compute_scores()

        total_n = len(scores)
        code_rank = {code: i + 1 for i, (code, _) in enumerate(
            sorted(scores.items(), key=lambda x: x[1], reverse=True)
        )}

        current_date = self.data.datetime.date(0)
        account_total_value = self.broker.get_value()          # 账户总市值（参考用）
        satellite_total_value = self._get_satellite_total_value()  # 卫星市值（约束计算用，>0才用）
        constraint_base_value = satellite_total_value if satellite_total_value > 1e3 else account_total_value
        current_positions = self._get_current_positions_mv(exclude_core=True)  # 只含卫星
        pending_sell_amounts = 0.0
        core_codes_set = set(self._core_positions.keys())
        # 过滤掉核心code：核心仓位永不参与轮动调仓
        selected_codes_filtered = [c for c in selected_codes if c not in core_codes_set]
        selected_set = set(selected_codes_filtered)
        # 动态单仓上限：当选中ETF数 < top_n 时，按比例放宽上限，避免现金滞留和反复超配减仓
        # 例：top_n=5 但仅选2只 → effective_max_pct = max(40%, 100/2) = 50%
        n_selected = max(len(selected_codes_filtered), 1)
        effective_max_pct = max(self.constraints.max_position_pct, 100.0 / n_selected)
        max_single_mv = constraint_base_value * effective_max_pct / 100

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
                sell_amount_real = pos.size * sell_price  # 实际卖出回款（含滑点下浮）
                self._log_trade(d, '卖出', pos.size, sell_price, reason_str)
                self.constraints.record_turnover(d._name, sell_amount, current_date)
                pending_sell_amounts += sell_amount_real
                self.close(d)

        # 1b. 减仓：仍在top_n但超配
        for d in self.datas:
            # 核心仓位永不调仓
            if d._name in core_codes_set:
                continue
            pos = self.getposition(d)
            if pos.size <= 0 or d._name not in selected_set:
                continue
            # 实际卫星持仓数不足top_n时，排名靠前的不强制减仓（避免现金滞留+反复踩踏）
            n_actual_positions = len(current_positions)
            if n_actual_positions < self.p.top_n:
                rank = code_rank.get(d._name, total_n)
                if rank <= n_actual_positions:
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
                                  f"（当前{current_mv/constraint_base_value*100:.1f}%→目标{effective_max_pct:.0f}%）")
                    sell_price = self.constraints.apply_slippage_sell(price)
                    sell_amount_real = sell_shares * sell_price
                    self._log_trade(d, '卖出', sell_shares, sell_price, reason_str)
                    self.constraints.record_turnover(d._name, sell_amount, current_date)
                    pending_sell_amounts += sell_amount_real
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
                        sell_amount_real = pos.size * sell_price
                        self._log_trade(d, '卖出', pos.size, sell_price, reason_str)
                        self.constraints.record_turnover(d._name, sell_amount, current_date)
                        pending_sell_amounts += sell_amount_real
                        self.close(d)

        # 阶段2：现金感知买入
        effective_cash = self.broker.get_cash() + pending_sell_amounts
        # 跟踪本轮买入pending市值（can_buy检查用），避免同轮多个买单向同行业超额
        pending_buy_updates: Dict[str, float] = {}

        for code in selected_codes_filtered:  # 用过滤后的
            d = self.getdatabyname(code)
            if d is None:
                continue
            price = d.close[0]
            if price <= 0:
                continue
            pos = self.getposition(d)
            current_mv = pos.size * price + pending_buy_updates.get(code, 0)
            buy_budget = max(0, max_single_mv - current_mv)
            buy_budget = min(buy_budget, effective_cash)
            if buy_budget <= 0:
                continue

            buy_price = self.constraints.apply_slippage_buy(price)
            target_size = int(buy_budget / buy_price / 100) * 100
            if target_size <= 0:
                continue
            buy_amount = target_size * buy_price

            # current_positions 含同轮pending买入，防止多ETF超限
            base_positions = self._get_current_positions_mv(exclude_core=True)
            current_positions = {k: v + pending_buy_updates.get(k, 0) for k, v in base_positions.items()}
            for pc, mv in pending_buy_updates.items():
                if pc not in current_positions:
                    current_positions[pc] = mv
            ok, reason = self.constraints.can_buy(
                code, buy_price, buy_amount, current_positions, constraint_base_value,
                current_date, effective_cash=effective_cash,
                code_to_sector=self.code_to_sector,
            )
            if not ok:
                continue
            ok_t, reason_t = self.constraints.check_turnover(
                buy_amount, constraint_base_value, current_date,
                allow_first_build=(len(base_positions) + len(pending_buy_updates)) == 0
            )
            if not ok_t:
                continue

            rank = code_rank.get(code, 0)
            score = scores.get(code, 0)
            raw = raw_factors.get(code, {})
            # bt.indicators 仅用于交易日志展示动量值（不参与因子打分）
            momentum_val = float(self.inds[d]['momentum'][0]) if d in self.inds and self.inds[d]['momentum'][0] is not None else 0
            pe_val = raw.get('pe_percentile', 0) or 0
            vol_val = raw.get('volatility_60d', 0) or 0
            reason_str = (f"多因子排名第{rank}/{total_n}，综合得分{score:.2f}，"
                          f"动量{momentum_val:.1f}%，PE百分位{pe_val:.0f}%，波动率{vol_val:.1f}%")
            self._log_trade(d, '买入', target_size, buy_price, reason_str)
            self.constraints.record_buy(code, current_date)
            self.constraints.record_turnover(code, buy_amount, current_date)
            self.buy(d, size=target_size, price=buy_price)
            pending_buy_updates[code] = pending_buy_updates.get(code, 0) + buy_amount
            effective_cash -= buy_amount

    def build_factor_diagnostics(self):
        """组装因子诊断结果，供回测输出

        Returns:
            dict with keys:
                factor_stats: DataFrame 每个因子的 IC/ICIR/胜率/状态/权重
                rolling_ic_series: DataFrame 滚动IC序列
                grouped_returns: dict 分组收益
                weight_history: DataFrame 权重历史
                weight_mode: str 加权模式
                excluded_factors: list 被剔除的因子及原因
        """
        import pandas as pd
        from strategy.scoring import FACTOR_LABELS, compute_icir_weights

        rows = []
        if self._factor_ic_history:
            w, excl, mode = compute_icir_weights(
                {k: list(v) for k, v in self._factor_ic_history.items()},
                rolling_months=12, return_mode=True
            )
        else:
            w, excl, mode = ({}, {}, 'equal_weight_fallback')

        for f, hist in self._factor_ic_history.items():
            arr = [x for x in hist if x is not None]
            m = float(np.mean(arr)) if arr else float('nan')
            s = float(np.std(arr, ddof=1)) if arr and len(arr) > 1 else float('nan')
            icir = (m / s) if s and not np.isnan(s) and s != 0 else 0.0
            hit = sum(1 for x in arr if x is not None and x > 0) / len(arr) if arr else 0.0
            status = 'excluded' if f in excl else 'active'
            used_w = w.get(f, 0.0)
            rows.append({
                'factor': f,
                'label': FACTOR_LABELS.get(f, f),
                'rank_ic_mean': m,
                'rank_ic_std': s,
                'icir': icir,
                'hit_rate_12m': hit,
                'status': status,
                'used_weight_mean': used_w,
                'excluded_months': 0,
            })
        factor_stats = pd.DataFrame(rows)
        rolling_ic_series = pd.DataFrame(self._ic_rolling_rows) if self._ic_rolling_rows else pd.DataFrame()
        weight_history = pd.DataFrame(self._weight_history_rows) if self._weight_history_rows else pd.DataFrame()

        excluded_list = [{'factor': f, 'reason': r, 'months': 0} for f, r in excl.items()]
        return {
            'factor_stats': factor_stats,
            'rolling_ic_series': rolling_ic_series,
            'grouped_returns': {},
            'weight_history': weight_history,
            'weight_mode': mode,
            'excluded_factors': excluded_list,
        }


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
