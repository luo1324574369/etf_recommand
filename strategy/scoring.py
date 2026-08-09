import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from strategy.factors.momentum import MomentumFactor
from strategy.factors.volatility import VolatilityFactor
from strategy.factors.liquidity import LiquidityFactor
from strategy.factors.valuation import ValuationPercentileFactor


FACTOR_DIRECTIONS = {
    "momentum_20d": -1,  # A股反转效应：短期超跌后续反弹
    "reversal_20d": 1,   # 20日反转因子：值越大越好（跌越多值越大）
    "momentum_120d": 1,  # 中长期动量效应
    "volatility_60d": -1,
    "avg_amount_20d": 1,
    "pe_percentile": -1,
    "pb_percentile": -1,
    "dividend_yield": 1,  # 红利因子：越高越好
    "cross_mom_120d": 1,   # NEW: 横截面120日动量,排名越高越好
}

DEFAULT_FACTORS = [
    "reversal_20d",
    "momentum_120d",    # rollback from cross_mom_120d
    "pe_percentile",
    "avg_amount_20d",
]

FACTOR_LABELS = {
    "momentum_20d": "20日动量(%)",
    "reversal_20d": "20日反转",
    "momentum_120d": "120日动量(%)",
    "volatility_60d": "60日波动率(%)",
    "avg_amount_20d": "20日日均成交额(万)",
    "pe_percentile": "PE百分位(%)",
    "pb_percentile": "PB百分位(%)",
    "dividend_yield": "股息率(%)",
    "cross_mom_120d": "横截面120日动量(百分位)",  # NEW
}


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def compute_all_factors(
    code: str,
    prices: List[dict],
    end_date: str = None,
    pe_percentile: float = None,
    pb_percentile: float = None,
    dividend_yield: float = None,
) -> Dict[str, float]:
    if not prices or len(prices) < 20:
        return {}

    latest_date = prices[-1]["trade_date"]
    if end_date is None:
        end_date = latest_date

    factors = {}

    for period in [20, 120]:
        f = MomentumFactor(period=period, name=f"momentum_{period}d")
        val = f.calculate(code, prices, end_date)
        if val is not None:
            factors[f"momentum_{period}d"] = _safe_float(val * 100)

    # 20日反转因子（统一使用 end_date 截断，与 MomentumFactor/VolatilityFactor 一致）
    rev20 = reversal_20d(prices, end_date=end_date)
    if rev20 is not None:
        factors['reversal_20d'] = rev20

    vf = VolatilityFactor(period=60)
    vresult = vf.calculate(code, prices, end_date)
    if isinstance(vresult, dict) and vresult.get("volatility") is not None:
        factors["volatility_60d"] = _safe_float(vresult["volatility"] * 100)

    lf = LiquidityFactor(period=20)
    lval = lf.calculate(code, prices, end_date)
    if lval is not None:
        factors["avg_amount_20d"] = _safe_float(lval)

    pf = ValuationPercentileFactor(metric="pe")
    pval = pf.calculate(code, prices, end_date, percentile=pe_percentile)
    if pval is not None:
        factors["pe_percentile"] = pval

    pbf = ValuationPercentileFactor(metric="pb")
    pbval = pbf.calculate(code, prices, end_date, percentile=pb_percentile)
    if pbval is not None:
        factors["pb_percentile"] = pbval

    # 红利因子（由外部传入，scoring不负责查库）
    if dividend_yield is not None:
        factors["dividend_yield"] = _safe_float(dividend_yield)

    return factors


def zscore_normalize(
    etf_factors: Dict[str, Dict[str, float]],
    factor_names: List[str] = None,
) -> Dict[str, Dict[str, float]]:
    if not etf_factors:
        return {}

    if factor_names is None:
        all_fs = set()
        for f in etf_factors.values():
            all_fs.update(f.keys())
        factor_names = sorted(all_fs)

    factor_values = {f: [] for f in factor_names}
    codes = list(etf_factors.keys())

    for code in codes:
        for f in factor_names:
            val = etf_factors[code].get(f)
            factor_values[f].append(val)

    zscores = {code: {} for code in codes}

    for f in factor_names:
        values = [v for v in factor_values[f] if v is not None]
        if len(values) < 2:
            for code in codes:
                zscores[code][f] = 0.0
            continue

        mean = np.mean(values)
        std = np.std(values, ddof=0)
        if std == 0 or np.isnan(std):
            for code in codes:
                zscores[code][f] = 0.0
            continue

        direction = FACTOR_DIRECTIONS.get(f, 1)
        for i, code in enumerate(codes):
            val = factor_values[f][i]
            if val is None:
                zscores[code][f] = 0.0
            else:
                z = (val - mean) / std * direction
                zscores[code][f] = float(np.clip(z, -3, 3))

    return zscores


def equal_weight_score(
    zscores: Dict[str, Dict[str, float]],
    factor_names: List[str] = None,
) -> Dict[str, float]:
    if not zscores:
        return {}

    if factor_names is None:
        all_fs = set()
        for f in zscores.values():
            all_fs.update(f.keys())
        factor_names = sorted(all_fs)

    scores = {}
    for code, fs in zscores.items():
        vals = [fs[f] for f in factor_names if f in fs]
        scores[code] = float(np.mean(vals)) if vals else 0.0

    return scores


def icir_weighted_score(
    zscores: Dict[str, Dict[str, float]],
    factor_icir: Dict[str, float],
    factor_names: List[str] = None,
) -> Dict[str, float]:
    if not zscores:
        return {}

    if factor_names is None:
        all_fs = set()
        for f in zscores.values():
            all_fs.update(f.keys())
        factor_names = sorted(all_fs)

    total_icir = sum(abs(factor_icir.get(f, 0)) for f in factor_names)
    if total_icir == 0:
        return equal_weight_score(zscores, factor_names)

    weights = {}
    for f in factor_names:
        icir_val = abs(factor_icir.get(f, 0))
        weights[f] = icir_val / total_icir

    scores = {}
    for code, fs in zscores.items():
        weighted_sum = 0.0
        for f in factor_names:
            if f in fs:
                weighted_sum += fs[f] * weights[f]
        scores[code] = float(weighted_sum)

    return scores


def weighted_score(
    zscores: Dict[str, Dict[str, float]],
    factor_weights: Dict[str, float],
    factor_names: List[str] = None,
) -> Dict[str, float]:
    if not zscores:
        return {}

    if factor_names is None:
        all_fs = set()
        for f in zscores.values():
            all_fs.update(f.keys())
        factor_names = sorted(all_fs)

    total_weight = sum(factor_weights.get(f, 0) for f in factor_names)
    if total_weight == 0:
        return equal_weight_score(zscores, factor_names)

    scores = {}
    for code, fs in zscores.items():
        weighted_sum = 0.0
        for f in factor_names:
            if f in fs and f in factor_weights:
                weighted_sum += fs[f] * factor_weights[f]
        scores[code] = float(weighted_sum / total_weight)

    return scores


def build_rank_table(
    etf_factors: Dict[str, Dict[str, float]],
    zscores: Dict[str, Dict[str, float]],
    scores: Dict[str, float],
    etf_names: Dict[str, str] = None,
    factor_names: List[str] = None,
) -> pd.DataFrame:
    if factor_names is None:
        all_fs = set()
        for f in etf_factors.values():
            all_fs.update(f.keys())
        factor_names = sorted(all_fs)

    rows = []
    for code in sorted(etf_factors.keys()):
        row = {"代码": code}
        if etf_names and code in etf_names:
            row["名称"] = etf_names[code]

        for f in factor_names:
            raw_val = etf_factors[code].get(f)
            z_val = zscores.get(code, {}).get(f)
            label = FACTOR_LABELS.get(f, f)
            if raw_val is not None:
                if f == "avg_amount_20d":
                    row[label] = round(raw_val / 10000, 0)
                else:
                    row[label] = round(raw_val, 2)
            else:
                row[label] = "-"

            if z_val is not None:
                row[f"{label}(Z)"] = round(z_val, 2)
            else:
                row[f"{label}(Z)"] = "-"

        row["综合评分"] = round(scores.get(code, 0), 2)
        rows.append(row)

    df = pd.DataFrame(rows)
    if "综合评分" in df.columns:
        df = df.sort_values("综合评分", ascending=False).reset_index(drop=True)
    return df


def compute_factor_history(
    code: str,
    prices: list,
    factor_names: list,
    pe_history: list = None,
    pb_history: list = None,
) -> pd.DataFrame:
    """
    逐日计算因子历史值。

    Args:
        code: ETF代码
        prices: 行情数据列表（按日期升序，每项含 trade_date, open, high, low, close, volume, amount）
        factor_names: 需要计算的因子名称列表（如 ['momentum_20d', 'volatility_60d', 'pe_percentile']）
        pe_history: PE历史数据列表（每项含 trade_date, pe 等），用于计算PE百分位时间序列
        pb_history: PB历史数据列表（每项含 trade_date, pb 等），用于计算PB百分位时间序列

    Returns:
        DataFrame with columns: date, factor1, factor2, ...
    """
    pe_pct_series = {}
    if pe_history:
        sorted_pe = sorted(pe_history, key=lambda x: x["trade_date"])
        pe_values = []
        for item in sorted_pe:
            pe_val = item.get("pe")
            if pe_val is not None and pe_val > 0:
                pe_values.append(pe_val)
                if len(pe_values) > 0:
                    rank = sum(1 for v in pe_values if v <= pe_val)
                    percentile = (rank / len(pe_values)) * 100
                    pe_pct_series[item["trade_date"]] = percentile

    pb_pct_series = {}
    if pb_history:
        sorted_pb = sorted(pb_history, key=lambda x: x["trade_date"])
        pb_values = []
        for item in sorted_pb:
            pb_val = item.get("pb")
            if pb_val is not None and pb_val > 0:
                pb_values.append(pb_val)
                if len(pb_values) > 0:
                    rank = sum(1 for v in pb_values if v <= pb_val)
                    percentile = (rank / len(pb_values)) * 100
                    pb_pct_series[item["trade_date"]] = percentile

    rows = []
    for i in range(len(prices)):
        sub_prices = prices[: i + 1]
        date = prices[i]["trade_date"]
        pe_pct = pe_pct_series.get(date) if pe_pct_series else None
        pb_pct = pb_pct_series.get(date) if pb_pct_series else None

        all_factors = compute_all_factors(code, sub_prices, pe_percentile=pe_pct, pb_percentile=pb_pct)

        row = {"date": date}
        for f in factor_names:
            row[f] = all_factors.get(f)
        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def winsorize_mad_3sigma(values: pd.Series) -> pd.Series:
    """截面MAD缩尾：clip(x, median-3*1.4826*MAD, median+3*1.4826*MAD)

    MAD对极端值鲁棒，优于均值-σ缩尾。和factor_analysis.py CLI对齐。
    """
    s = values.copy()
    if len(s.dropna()) < 2:
        return s
    arr = np.array(s.values, dtype=float)
    valid = ~np.isnan(arr)
    if valid.sum() < 2:
        return s
    v = arr[valid]
    median = np.nanmedian(v)
    mad = np.nanmedian(np.abs(v - median))
    if mad == 0 or np.isnan(mad):
        return s
    k = 3
    half_width = k * 1.4826 * mad
    lower = median - half_width
    upper = median + half_width
    arr[valid] = np.clip(v, lower, upper)
    s = pd.Series(arr, index=s.index)
    return s


def group_zscore(etf_codes, factor_values, code_to_group):
    """赛道/宽基分组zscore，返回 dict[code]=zscore。
    单组<2个ETF的降级到全局zscore。
    """
    # 收集
    group_to_vals = {}
    for c in etf_codes:
        g = code_to_group.get(c, '其他')
        group_to_vals.setdefault(g, []).append((c, factor_values.get(c, np.nan)))
    out = {}
    global_vals = []
    global_pairs = []
    for g, pairs in group_to_vals.items():
        vals = np.array([v for _, v in pairs], dtype=float)
        n_valid = np.sum(~np.isnan(vals))
        if n_valid < 2:
            # 降级
            for c, v in pairs:
                global_pairs.append((c, v))
                global_vals.append(v)
            continue
        mean = np.nanmean(vals)
        std = np.nanstd(vals, ddof=1)
        if std == 0 or np.isnan(std):
            zs = np.zeros_like(vals)
        else:
            zs = (vals - mean) / std
        for (c, _), z in zip(pairs, zs):
            if np.isnan(z):
                out[c] = 0.0
            else:
                out[c] = float(z)
    # 处理降级部分 - 单组过小时按全局所有ETF的分布做zscore
    if global_pairs:
        all_vals = np.array([factor_values.get(c, np.nan) for c in etf_codes], dtype=float)
        if np.sum(~np.isnan(all_vals)) >= 2:
            mean = np.nanmean(all_vals)
            std = np.nanstd(all_vals, ddof=1)
            if std and not np.isnan(std):
                fb_vals = np.array([v for _, v in global_pairs], dtype=float)
                zs = (fb_vals - mean) / std
                for (c, v), z in zip(global_pairs, zs):
                    out[c] = 0.0 if np.isnan(z) else float(z)
                return out
        for c, v in global_pairs:
            out[c] = 0.0
    return out


def reversal(prices, period=20, end_date=None):
    """反转因子 = -(close_t / close_{t-period} - 1)
    跌越多 → 值越大 → direction=+1 正向因子
    prices: list[dict] 至少 period+1 条
    end_date: str 'YYYY-MM-DD'，仅使用 <= end_date 的数据（防未来数据泄漏）
    """
    if not prices or len(prices) < period + 1:
        return None
    if end_date is not None:
        prices = [p for p in prices if p['trade_date'] <= end_date]
    if len(prices) < period + 1:
        return None
    closes = [p['close'] for p in prices]
    if closes[-(period + 1)] == 0:
        return None
    return float(-(closes[-1] / closes[-(period + 1)] - 1))


def reversal_20d(prices, end_date=None):
    """20日反转因子（向后兼容别名）"""
    return reversal(prices, period=20, end_date=end_date)


def cross_sectional_momentum(
    all_etf_returns: dict,
    periods: list = None,
) -> dict:
    """横截面动量:在N只ETF池子里按N日收益率排名→百分位(0~100)。

    国君/华泰金工ETF回测验证:横截面RankIC=+0.04~+0.06,
    是时序动量(momentum_120d IC=+0.01)的3-5倍。
    小截面(33只)下排名百分位比绝对收益率噪声小得多。

    Args:
        all_etf_returns: {code: {period_days: raw_return_float}}
                         原始收益率(小数,如+0.15=15%);允许缺period
        periods: 计算的周期列表,默认[120]

    Returns:
        {code: {f"cross_mom_{p}d": percentile_0_100_float or None}}

    边界条件(参考Experience 372222动量≈0中性处理):
    • ε中性: |收益率| < 1e-6 时视为平局,赋中位百分位=50.0,避免浮点噪声翻转排名
    • Tie处理: numpy默认argsort平局用平均index→百分位取中位rank
    • 缺失值/数据不足: 返回None,后续zscore→0,与现有因子缺失行为一致
    • 仅1只ETF有效时: 返回50.0(没有排名语义,中性化)
    """
    if periods is None:
        periods = [120]
    result = {}
    EPS = 1e-6
    for p in periods:
        key = f"cross_mom_{p}d"
        pairs = []
        for code, period_map in all_etf_returns.items():
            r = period_map.get(p)
            if r is None or (isinstance(r, float) and np.isnan(r)):
                continue
            pairs.append((code, float(r)))
        if not pairs:
            continue
        flat_pairs = [(c, 0.0) if abs(v) < EPS else (c, v) for c, v in pairs]
        codes = [c for c, _ in flat_pairs]
        values = np.array([v for _, v in flat_pairs], dtype=float)
        n = len(codes)
        if n < 2:
            for c in codes:
                result.setdefault(c, {})[key] = 50.0
            continue
        try:
            from scipy import stats as _sc
            ranks = _sc.rankdata(values, method='average')
        except ImportError:
            order = np.argsort(values)
            ranks = np.empty_like(order, dtype=float)
            ranks[order] = np.arange(1, n + 1, dtype=float)
        percentiles = (ranks - 1) / (n - 1) * 100.0 if n > 1 else np.full(n, 50.0)
        for code, pct in zip(codes, percentiles):
            result.setdefault(code, {})[key] = float(pct)
    return result


from scipy import stats as _sp_stats
from collections import deque


def rank_ic_monthly(factor_ranks_series, next_return_ranks_series):
    """月度截面RankIC = Spearman秩相关系数。
    输入是截面（非时间序列）对齐后的两列排名/值均可（spearman自动转秩）。
    """
    if len(factor_ranks_series) < 3:
        return None
    common_idx = factor_ranks_series.dropna().index.intersection(next_return_ranks_series.dropna().index)
    if len(common_idx) < 3:
        return None
    f = factor_ranks_series.loc[common_idx].astype(float)
    r = next_return_ranks_series.loc[common_idx].astype(float)
    if f.std(ddof=0) == 0 or r.std(ddof=0) == 0:
        return None
    coef, _ = _sp_stats.spearmanr(f.values, r.values)
    if np.isnan(coef):
        return None
    return float(coef)


def compute_icir_weights(ic_history, rolling_months=12,
                         min_icir_include=0.02,
                         return_mode=False):
    """方向感知ICIR加权 + 指数衰减 + 贝叶斯收缩 + 连续8月≤0剔除。

    核心改进（vs 旧版）：
    1. 方向修复：raw IC × FACTOR_DIRECTIONS[factor] 后再算 ICIR
    2. 阈值降低：min_icir_include 0.05 → 0.02（33ETF月度截面IC天然偏小）
    3. 指数衰减：half-life=6月，近期IC权重更高
    4. 贝叶斯收缩：ICIR向截面中位数收缩（κ=3），避免小样本极端值
    5. 连续8月≤0剔除（原6月，适应A股牛熊周期）
    6. Fallback：全负时保留方向调整后ICIR最高的2个因子（原等权）

    Args:
        ic_history: {factor: list[float]} 按时间升序的月度IC序列（新值在末尾）
        rolling_months: 使用最近N个月
        min_icir_include: ICIR < 此值也视为弱因子，权重=0
        return_mode: True时返回三元组 (weights, excluded, mode)；否则二元组
    Returns:
        weights: {factor: float} 所有权重（含被剔除的也放进去但=0）；总和=1.0
        excluded: {factor: str} 被剔除的原因标签
        mode: 'icir_dynamic' | 'equal_weight_fallback' （仅当return_mode=True）
    """
    trimmed = {}
    for k, lst in ic_history.items():
        if not lst:
            continue
        arr = list(lst)[-rolling_months:]
        trimmed[k] = [v if v is not None else np.nan for v in arr]
    all_factors = list(trimmed.keys())
    weights = {f: 0.0 for f in all_factors}
    excluded = {}
    excluded_raw = set()

    # 连续8月方向调整后IC≤0 判定（原6月，放宽以适应A股牛熊周期）
    for f, arr in trimmed.items():
        valid_arr = [v for v in arr if not np.isnan(v)]
        if len(valid_arr) >= 8:
            direction = FACTOR_DIRECTIONS.get(f, 1)
            last8_adj = [v * direction for v in valid_arr[-8:]]
            if all(x <= 0 for x in last8_adj):
                excluded[f] = 'consecutive_8m_adj_ic_le_0'
                excluded_raw.add(f)

    # 方向调整 + 指数衰减 + 贝叶斯收缩 计算ICIR
    icir_scores = {}        # 原始ICIR
    adj_icir_scores = {}    # 方向调整后ICIR（用于排序和权重）
    for f, arr in trimmed.items():
        if f in excluded_raw:
            continue
        valid_arr = [v for v in arr if not np.isnan(v)]
        if len(valid_arr) < 3:
            continue
        direction = FACTOR_DIRECTIONS.get(f, 1)
        adj_ic = [v * direction for v in valid_arr]

        # 指数衰减权重（half-life=6月，近期更重要）
        n = len(adj_ic)
        time_weights = [0.5 ** ((n - 1 - i) / 6) for i in range(n)]
        w_sum = sum(time_weights)
        ew_mean = sum(w * v for w, v in zip(time_weights, adj_ic)) / w_sum
        ew_var = sum(w * (v - ew_mean) ** 2 for w, v in zip(time_weights, adj_ic)) / w_sum
        ew_std = ew_var ** 0.5
        if ew_std == 0 or np.isnan(ew_std):
            continue

        adj_icir = ew_mean / ew_std
        raw_icir = float(np.mean(valid_arr)) / float(np.std(valid_arr, ddof=1))
        icir_scores[f] = raw_icir
        adj_icir_scores[f] = adj_icir

        if adj_icir < 0:
            continue
        if adj_icir < min_icir_include:
            continue

    # 贝叶斯收缩：ICIR向截面中位数收缩（κ=3）
    # 判定用收缩前raw_adj（真实信号强度），数值用收缩后shrunk（避免极端值）
    positive_adj = [v for v in adj_icir_scores.values() if v > 0]
    if len(positive_adj) >= 2:
        prior = float(np.median(positive_adj))
    else:
        prior = 0.0
    kappa = 3
    shrunk_icir = {}
    for f in adj_icir_scores:
        if f in excluded_raw:
            continue
        valid_arr = [v for v in trimmed[f] if not np.isnan(v)]
        n = len(valid_arr)
        raw_adj = adj_icir_scores[f]
        shrunk = (n * raw_adj + kappa * prior) / (n + kappa)
        # 判定用收缩前（真实信号强度），数值用收缩后（稳健估计）
        if raw_adj >= min_icir_include:
            shrunk_icir[f] = max(shrunk, min_icir_include * 0.5)

    mode = 'icir_dynamic'
    total_pos = sum(shrunk_icir.values())
    if total_pos <= 0:
        # Fallback：保留方向调整后ICIR最高的2个因子（非等权）
        mode = 'equal_weight_fallback'
        ranked = sorted(adj_icir_scores.items(), key=lambda x: x[1], reverse=True)
        for f, _ in ranked[:2]:
            weights[f] = 0.5
    else:
        for f, score in shrunk_icir.items():
            weights[f] = score / total_pos

    if return_mode:
        return weights, excluded, mode
    return weights, excluded
