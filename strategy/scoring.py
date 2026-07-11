import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from strategy.factors.momentum import MomentumFactor
from strategy.factors.volatility import VolatilityFactor
from strategy.factors.liquidity import LiquidityFactor
from strategy.factors.valuation import ValuationPercentileFactor


FACTOR_DIRECTIONS = {
    "momentum_20d": 1,
    "momentum_60d": 1,
    "momentum_120d": 1,
    "volatility_60d": -1,
    "avg_amount_20d": 1,
    "pe_percentile": -1,
    "pb_percentile": -1,
}

DEFAULT_FACTORS = [
    "momentum_60d",
    "momentum_120d",
    "pe_percentile",
    "avg_amount_20d",
]

FACTOR_LABELS = {
    "momentum_20d": "20日动量(%)",
    "momentum_60d": "60日动量(%)",
    "momentum_120d": "120日动量(%)",
    "volatility_60d": "60日波动率(%)",
    "avg_amount_20d": "20日日均成交额(万)",
    "pe_percentile": "PE百分位(%)",
    "pb_percentile": "PB百分位(%)",
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
) -> Dict[str, float]:
    if not prices or len(prices) < 20:
        return {}

    latest_date = prices[-1]["trade_date"]
    if end_date is None:
        end_date = latest_date

    factors = {}

    for period in [20, 60, 120]:
        f = MomentumFactor(period=period, name=f"momentum_{period}d")
        val = f.calculate(code, prices, end_date)
        if val is not None:
            factors[f"momentum_{period}d"] = _safe_float(val * 100)

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
