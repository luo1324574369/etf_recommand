"""因子有效性检验工具

提供RankIC、ICIR、分层回测等因子检验指标，支持命令行独立运行。
"""
from typing import Dict, List

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def compute_forward_returns(prices: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算每只ETF每个日期的period日前瞻收益

    Args:
        prices: columns=['trade_date', 'code', 'close']
        period: 前瞻周期（交易日）

    Returns:
        DataFrame, columns=['trade_date', 'code', 'forward_return']
    """
    df = prices.sort_values(['code', 'trade_date']).copy()
    df['future_close'] = df.groupby('code')['close'].shift(-period)
    df['forward_return'] = (df['future_close'] - df['close']) / df['close']
    return df[['trade_date', 'code', 'forward_return']].dropna()


def compute_rank_ic(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_names: List[str],
    method: str = 'spearman',
) -> pd.DataFrame:
    """计算月度截面RankIC序列

    Args:
        factor_values: columns=['date', 'code', factor1, factor2, ...]
        forward_returns: columns=['date', 'code', 'forward_return']
        factor_names: 需计算的因子名列表
        method: 'spearman' (RankIC) or 'pearson' (IC)

    Returns:
        DataFrame, columns=['date', 'factor_name', 'ic']
    """
    merged = pd.merge(factor_values, forward_returns, on=['date', 'code'])

    rows = []
    for date in sorted(merged['date'].unique()):
        day_data = merged[merged['date'] == date]
        if len(day_data) < 5:
            continue
        for factor in factor_names:
            if factor not in day_data.columns:
                continue
            valid = day_data[[factor, 'forward_return']].dropna()
            if len(valid) < 5:
                continue
            if method == 'spearman':
                corr, _ = spearmanr(valid[factor], valid['forward_return'])
            else:
                corr = valid[factor].corr(valid['forward_return'])
            if not np.isnan(corr):
                rows.append({'date': date, 'factor_name': factor, 'ic': corr})

    if not rows:
        return pd.DataFrame(columns=['date', 'factor_name', 'ic'])
    return pd.DataFrame(rows)


def compute_icir(ic_series: pd.Series) -> Dict:
    """计算单因子的ICIR

    Returns:
        {'ic_mean', 'ic_std', 'icir', 'ic_positive_ratio', 'ic_t_stat'}
    """
    if len(ic_series) == 0:
        return {'ic_mean': 0, 'ic_std': 0, 'icir': 0, 'ic_positive_ratio': 0, 'ic_t_stat': 0}

    ic_mean = float(ic_series.mean())
    ic_std = float(ic_series.std(ddof=1))
    icir = ic_mean / ic_std if ic_std > 0 else 0
    ic_positive_ratio = float((ic_series > 0).sum() / len(ic_series))
    ic_t_stat = ic_mean / (ic_std / np.sqrt(len(ic_series))) if ic_std > 0 else 0

    return {
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        'ic_positive_ratio': ic_positive_ratio,
        'ic_t_stat': float(ic_t_stat),
    }


def compute_rolling_ic(
    ic_df: pd.DataFrame,
    rolling_window_months: int = 24,
    min_samples: int = 12,
) -> pd.DataFrame:
    """计算滚动IC序列（滚动窗口内的ICIR）

    Args:
        ic_df: columns=['date', 'factor_name', 'ic']
        rolling_window_months: 滚动窗口（月），默认24个月
        min_samples: 窗口内最少IC样本数

    Returns:
        DataFrame, columns=['date', 'factor_name', 'rolling_ic_mean', 'rolling_ic_std', 
                           'rolling_icir', 'rolling_ic_positive_ratio']
    """
    df = ic_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['factor_name', 'date'])

    results = []
    for factor in df['factor_name'].unique():
        factor_df = df[df['factor_name'] == factor].copy()
        if len(factor_df) < min_samples:
            continue

        window_days = rolling_window_months * 30
        for i in range(len(factor_df)):
            end_date = factor_df.iloc[i]['date']
            start_date = end_date - pd.Timedelta(days=window_days)
            window_data = factor_df[(factor_df['date'] >= start_date) & (factor_df['date'] <= end_date)]
            if len(window_data) < min_samples:
                continue

            ic_vals = window_data['ic']
            ic_mean = float(ic_vals.mean())
            ic_std = float(ic_vals.std(ddof=1))
            icir = ic_mean / ic_std if ic_std > 0 else 0
            ic_positive_ratio = float((ic_vals > 0).sum() / len(ic_vals))

            results.append({
                'date': end_date,
                'factor_name': factor,
                'rolling_ic_mean': ic_mean,
                'rolling_ic_std': ic_std,
                'rolling_icir': icir,
                'rolling_ic_positive_ratio': ic_positive_ratio,
            })

    return pd.DataFrame(results)


def stratified_backtest(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_name: str,
    n_groups: int = 5,
) -> pd.DataFrame:
    """分层回测：按因子值分组，计算各组未来收益

    Args:
        factor_values: columns=['date', 'code', factor_name]
        forward_returns: columns=['date', 'code', 'forward_return']
        factor_name: 因子名
        n_groups: 分组数

    Returns:
        DataFrame, columns=['date', 'group', 'avg_return']
        group=1是因子值最低组，group=n_groups是最高组
    """
    merged = pd.merge(factor_values, forward_returns, on=['date', 'code'])

    rows = []
    for date in sorted(merged['date'].unique()):
        day_data = merged[merged['date'] == date].copy()
        if len(day_data) < n_groups:
            continue
        valid = day_data[[factor_name, 'forward_return']].dropna()
        if len(valid) < n_groups:
            continue
        valid['group'] = pd.qcut(valid[factor_name], n_groups, labels=False, duplicates='drop') + 1
        for g in sorted(valid['group'].unique()):
            group_data = valid[valid['group'] == g]
            rows.append({
                'date': date,
                'group': int(g),
                'avg_return': float(group_data['forward_return'].mean()),
            })

    return pd.DataFrame(rows)


def _judge_verdict(ic_mean: float, icir: float, ic_positive_ratio: float,
                   monotonic: bool, direction: int = 1) -> str:
    """判定因子有效性（支持因子方向）

    判定逻辑：5个指标中≥2个达到"有效"判为有效，
    ≥2个达到"弱有效+"判为弱有效，否则无效。

    Args:
        ic_mean: RankIC均值
        icir: ICIR
        ic_positive_ratio: IC为正的比例
        monotonic: 是否单调
        direction: 因子方向，1=正向（值越大越好），-1=反向（值越小越好）
    """
    abs_ic = abs(ic_mean)
    effective_count = 0
    weak_count = 0

    # 指标1：方向匹配（IC符号与预期方向一致）
    if (direction == 1 and ic_mean > 0) or (direction == -1 and ic_mean < 0):
        effective_count += 1

    # 指标2：RankIC绝对值
    if abs_ic >= 0.03:
        effective_count += 1
    elif abs_ic >= 0.015:
        weak_count += 1

    # 指标3：ICIR绝对值
    abs_icir = abs(icir)
    if abs_icir >= 0.15:
        effective_count += 1
    elif abs_icir >= 0.075:
        weak_count += 1

    # 指标4：IC正确比例（反向因子用 1 - ic_positive_ratio）
    if direction == -1:
        ic_correct_ratio = 1 - ic_positive_ratio
    else:
        ic_correct_ratio = ic_positive_ratio

    if ic_correct_ratio >= 0.55:
        effective_count += 1
    elif ic_correct_ratio >= 0.50:
        weak_count += 1

    # 指标5：单调性
    if monotonic:
        effective_count += 1

    if effective_count >= 2:
        return '有效'
    elif weak_count + effective_count >= 2:
        return '弱有效'
    return '无效'


def _check_monotonicity(strat_df: pd.DataFrame, n_groups: int = 5) -> tuple:
    """检查分层收益是否单调（行业标准：Spearman |rho|>=0.7 或 反转次数<=1）

    Returns:
        (is_monotonic: bool, spearman_rho: float)
            is_monotonic=True 代表分组收益有稳定的单方向梯度
            spearman_rho: 组号(1~N)与平均收益的秩相关系数，|rho|越大梯度越明显
    """
    if strat_df.empty:
        return False, 0.0
    avg_by_group = strat_df.groupby('group')['avg_return'].mean()
    if len(avg_by_group) < n_groups:
        return False, 0.0
    values = avg_by_group.values
    groups = np.arange(1, len(values) + 1)

    rho, _ = spearmanr(groups, values)
    if np.isnan(rho):
        rho = 0.0

    n_violations_inc = sum(1 for i in range(len(values) - 1) if values[i] > values[i + 1])
    n_violations_dec = sum(1 for i in range(len(values) - 1) if values[i] < values[i + 1])
    n_violations = min(n_violations_inc, n_violations_dec)

    is_monotonic = (abs(rho) >= 0.7) or (n_violations <= 1)
    return is_monotonic, float(rho)


def analyze_factor(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_name: str,
    n_groups: int = 5,
    direction: int = None,
) -> Dict:
    """单因子全量检验

    Args:
        direction: 因子方向，1=正向，-1=反向，None=从FACTOR_DIRECTIONS查询

    Returns:
        {ic_series, icir, stratified, monotonicity, verdict, ic_mean, ic_positive_ratio}
    """
    from strategy.scoring import FACTOR_DIRECTIONS

    if direction is None:
        direction = FACTOR_DIRECTIONS.get(factor_name, 1)

    ic_df = compute_rank_ic(factor_values, forward_returns, [factor_name])
    ic_series = ic_df[ic_df['factor_name'] == factor_name]['ic']
    if len(ic_series) == 0:
        # 检查因子值是否全为 NaN（数据缺失）还是有效数据不足
        factor_col = factor_values[factor_name].dropna() if factor_name in factor_values.columns else pd.Series()
        if len(factor_col) == 0:
            # 因子完全无数据：数据缺失，非因子无效
            return {
                'ic_series': [],
                'icir': {'ic_mean': 0, 'ic_std': 0, 'icir': 0,
                         'ic_positive_ratio': 0, 'ic_t_stat': 0},
                'stratified': [],
                'monotonicity': '无数据',
                'spearman_rho': 0.0,
                'verdict': '无数据',
                'ic_mean': 0,
                'ic_positive_ratio': 0,
            }
        # 有因子数据但无法计算IC（样本不足）
        return {
            'ic_series': [],
            'icir': {'ic_mean': 0, 'ic_std': 0, 'icir': 0,
                     'ic_positive_ratio': 0, 'ic_t_stat': 0},
            'stratified': [],
            'monotonicity': '非单调',
            'spearman_rho': 0.0,
            'verdict': '无效',
            'ic_mean': 0,
            'ic_positive_ratio': 0,
        }
    icir_result = compute_icir(ic_series)
    strat_df = stratified_backtest(factor_values, forward_returns, factor_name, n_groups)
    monotonic, spearman_rho = _check_monotonicity(strat_df, n_groups)

    verdict = _judge_verdict(
        icir_result['ic_mean'], icir_result['icir'],
        icir_result['ic_positive_ratio'], monotonic, direction
    )

    mono_label = '单调' if monotonic else '非单调'

    return {
        'ic_series': ic_df.to_dict('records'),
        'icir': icir_result,
        'stratified': strat_df.to_dict('records'),
        'monotonicity': mono_label,
        'spearman_rho': spearman_rho,
        'verdict': verdict,
        'ic_mean': icir_result['ic_mean'],
        'ic_positive_ratio': icir_result['ic_positive_ratio'],
    }


def sample_by_trading_day(
    df: pd.DataFrame,
    freq_days: int = 10,
    date_col: str = 'date',
    group_col: str = 'code',
    date_to_idx: Dict = None,
) -> pd.DataFrame:
    """按全局交易日序号采样（每freq_days天取最后一天）

    保证所有ETF在同一bucket内对应同一日期范围（横截面对齐）。

    Args:
        df: 含date列和code列的DataFrame
        freq_days: 每多少个交易日采样一次
        date_col: 日期列名
        group_col: 分组列名（如code）
        date_to_idx: 可选，外部传入的日期→序号映射。
            若提供则使用此映射（保证多次采样对齐），否则从df内部计算。

    Returns:
        采样后的DataFrame，含sample_bucket列
    """
    df = df.copy()
    if date_to_idx is None:
        all_dates = sorted(df[date_col].unique())
        date_to_idx = {d: i for i, d in enumerate(all_dates)}
    df['sample_bucket'] = df[date_col].map(date_to_idx) // freq_days
    sampled = df.groupby(['sample_bucket', group_col]).last().reset_index()
    return sampled


def validate_pe_data(
    pe_by_code: Dict[str, Dict[str, float]],
    min_records: int = 100,
) -> None:
    """校验PE数据完整性，不满足则抛出RuntimeError

    Args:
        pe_by_code: {code: {trade_date: pe_value}}
        min_records: 最少有效PE记录数（pe>0）

    Raises:
        RuntimeError: 数据不完整时抛出
    """
    for code, pe_map in pe_by_code.items():
        valid_count = sum(1 for v in pe_map.values() if v is not None and v > 0)
        if valid_count == 0:
            raise RuntimeError(
                f"ETF {code} PE 历史数据缺失，无法进行因子有效性检验。"
                f"请先运行数据补充脚本。"
            )
        if valid_count < min_records:
            raise RuntimeError(
                f"ETF {code} PE 历史数据仅 {valid_count} 条，"
                f"不足以计算百分位（要求≥{min_records}条）。"
            )


def compute_cross_sectional_pe_percentile(
    pe_by_code: Dict[str, Dict[str, float]],
    all_dates: List[str],
    min_etfs: int = 5,
) -> Dict[str, Dict[str, float]]:
    """计算PE横截面百分位

    Args:
        pe_by_code: {code: {trade_date: pe_value}}
        all_dates: 所有交易日列表（按日期升序）
        min_etfs: 最少有效ETF数，不足则跳过该日

    Returns:
        {trade_date: {code: percentile}}
        percentile 范围 0-100
    """
    result = {}
    last_pe = {code: None for code in pe_by_code}

    for date in all_dates:
        for code in pe_by_code:
            pe_val = pe_by_code[code].get(date)
            if pe_val is not None and pe_val > 0:
                last_pe[code] = pe_val

        valid_pes = {
            c: last_pe[c]
            for c in pe_by_code
            if last_pe[c] is not None and last_pe[c] > 0
        }
        if len(valid_pes) < min_etfs:
            continue

        sorted_pes = sorted(valid_pes.values())
        for code, pe_val in valid_pes.items():
            rank = sum(1 for v in sorted_pes if v <= pe_val)
            result.setdefault(date, {})[code] = (rank / len(sorted_pes)) * 100

    return result


def analyze_all_etfs(
    etf_codes: List[str],
    price_repo,
    valuation_repo,
    start_date: str,
    end_date: str,
    factor_names: List[str] = None,
    forward_period: int = 60,
    sample_freq_days: int = 10,
    min_pe_records: int = 100,
) -> Dict:
    """全ETF池因子检验汇总

    Args:
        etf_codes: ETF代码列表
        price_repo: PriceRepository实例
        valuation_repo: ValuationRepo实例
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        factor_names: 因子名列表，None=默认['reversal_20d', 'pe_percentile', 'volatility_60d']
        forward_period: 前瞻周期（交易日），默认60日
        sample_freq_days: 采样频率（每N个交易日采样一次），默认10日
        min_pe_records: 最少PE历史记录数，默认100条

    Returns:
        {factor_name: {ic_mean, icir, ic_positive_ratio, monotonicity, verdict, ic_series, stratified}}
    """
    from strategy.scoring import compute_all_factors

    if factor_names is None:
        factor_names = ['reversal_20d', 'pe_percentile', 'volatility_60d']

    has_pe_factor = any('pe' in f for f in factor_names)
    has_dy_factor = any(f == 'dividend_yield' for f in factor_names)

    # ── 步骤 1: 收集所有ETF的行情数据 ──
    all_prices_by_code = {}
    all_factor_rows = []
    all_return_rows = []
    all_price_dfs = []
    pe_history_by_code = {}
    dy_history_by_code = {}  # {code: {trade_date: dividend_yield}}

    for code in etf_codes:
        if hasattr(price_repo, "get_signal_price"):
            prices = price_repo.get_signal_price(code)
        else:
            prices = price_repo.get_daily_price(code)
        if not prices or len(prices) < 120:
            continue

        df = pd.DataFrame(prices)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date')
        df = df[(df['trade_date'] >= start_date) & (df['trade_date'] <= end_date)]

        if len(df) < 120:
            continue

        all_prices_by_code[code] = df

        # ── 收集PE历史（用于横截面百分位） ──
        if has_pe_factor and hasattr(valuation_repo, 'get_pe_history'):
            pe_history = valuation_repo.get_pe_history(code)
            if pe_history:
                pe_map = {
                    item['trade_date']: item.get('pe')
                    for item in pe_history
                    if item.get('pe') is not None and item.get('pe') > 0
                }
                pe_history_by_code[code] = pe_map

        # ── 收集股息率历史（用于传入compute_all_factors） ──
        if has_dy_factor and hasattr(valuation_repo, 'get_valuation'):
            dy_history = valuation_repo.get_valuation(code)
            if dy_history:
                dy_map = {}
                for item in dy_history:
                    dy = item.get('dividend_yield')
                    if dy is not None and dy > 0:
                        dy_map[item['trade_date']] = float(dy)
                if dy_map:
                    dy_history_by_code[code] = dy_map

        # ── 逐日计算因子值（动量、波动率等非PE因子） ──
        prices_list = df.to_dict('records')
        dy_map = dy_history_by_code.get(code, {})
        # 股息率按日期前向填充：维护最近一次有效值
        last_dy = None
        for i in range(60, len(prices_list)):
            sub_prices = prices_list[:i + 1]
            current_date = prices_list[i]['trade_date']
            current_date_str = current_date.strftime('%Y-%m-%d') if hasattr(current_date, 'strftime') else str(current_date)

            # 前向填充股息率
            if dy_map:
                if current_date_str in dy_map:
                    last_dy = dy_map[current_date_str]

            factors = compute_all_factors(
                code, sub_prices, pe_percentile=None,
                dividend_yield=last_dy,
            )

            row = {'date': current_date, 'code': code}
            for f in factor_names:
                if 'pe' not in f:
                    row[f] = factors.get(f)
            all_factor_rows.append(row)

        price_df = df[['trade_date', 'close']].copy()
        price_df['code'] = code
        all_price_dfs.append(price_df)

    if not all_factor_rows or not all_price_dfs:
        return {}

    factor_df = pd.DataFrame(all_factor_rows)
    prices_df = pd.concat(all_price_dfs, ignore_index=True)

    # ── 步骤 2: 计算PE横截面百分位并合并到因子表 ──
    if has_pe_factor and pe_history_by_code:
        # 严格模式校验
        validate_pe_data(pe_history_by_code, min_records=min_pe_records)

        # 获取所有行情日期（字符串格式）
        all_trade_dates = sorted(factor_df['date'].unique())
        all_trade_dates_str = [pd.Timestamp(d).strftime('%Y-%m-%d') for d in all_trade_dates]

        # 计算横截面PE百分位
        pe_cs = compute_cross_sectional_pe_percentile(
            pe_history_by_code, all_trade_dates_str, min_etfs=5
        )

        # 合并PE百分位到factor_df
        pe_rows = []
        for date_str, code_pcts in pe_cs.items():
            date_ts = pd.Timestamp(date_str)
            for code, pct in code_pcts.items():
                pe_rows.append({'date': date_ts, 'code': code, 'pe_percentile': pct})

        if pe_rows:
            pe_df = pd.DataFrame(pe_rows)
            factor_df = pd.merge(factor_df, pe_df, on=['date', 'code'], how='left')

    # ── 步骤 3: 计算前瞻收益 ──
    forward_df = compute_forward_returns(prices_df, period=forward_period)

    # ── 步骤 4: 按交易日序号采样（使用统一date_to_idx映射） ──
    # 建立所有日期的全局序号映射（factor_df 和 forward_df 共用）
    all_dates_union = sorted(
        set(factor_df['date'].unique()) | set(forward_df['trade_date'].unique())
    )
    date_to_idx = {d: i for i, d in enumerate(all_dates_union)}

    sampled_factor = sample_by_trading_day(
        factor_df, freq_days=sample_freq_days, date_to_idx=date_to_idx
    )

    # forward_df 也按同样映射采样
    forward_df_copy = forward_df.copy()
    forward_df_copy['date'] = forward_df_copy['trade_date']
    sampled_forward = sample_by_trading_day(
        forward_df_copy, freq_days=sample_freq_days,
        date_col='date', date_to_idx=date_to_idx
    )

    # ── 步骤 5: 对每个因子做检验（考虑因子方向） ──
    from strategy.scoring import FACTOR_DIRECTIONS

    result = {}
    for factor in factor_names:
        if factor not in sampled_factor.columns:
            continue
        direction = FACTOR_DIRECTIONS.get(factor, 1)
        result[factor] = analyze_factor(
            sampled_factor[['date', 'code', factor]],
            sampled_forward[['date', 'code', 'forward_return']],
            factor,
            direction=direction,
        )

    return result


def main():
    """命令行入口"""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description='因子有效性检验')
    parser.add_argument('--factor', type=str, default=None, help='单个因子名')
    parser.add_argument('--all', action='store_true', help='检验所有因子')
    parser.add_argument('--start', type=str, default='2019-01-01', help='开始日期')
    parser.add_argument('--end', type=str, default='2024-12-31', help='结束日期')
    parser.add_argument('--output', type=str, default=None, help='输出JSON文件路径')
    args = parser.parse_args()

    sys.path.insert(0, '.')

    from data.storage.db import init_db, get_db
    from data.storage.price_repo import PriceRepository
    from data.storage.valuation_repo import ValuationRepo
    from config.settings import ETF_UNIVERSE, DB_PATH

    init_db(DB_PATH)
    price_repo = PriceRepository(get_db(DB_PATH))
    valuation_repo = ValuationRepo(str(DB_PATH))

    etf_codes = [e['code'] for e in ETF_UNIVERSE]
    report = analyze_all_etfs(etf_codes, price_repo, valuation_repo, args.start, args.end)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"报告已保存到 {args.output}")
    else:
        print(f"\n{'='*60}")
        print(f"因子有效性分析报告 ({args.start} ~ {args.end})")
        print(f"ETF数: {len(etf_codes)}")
        print(f"{'='*60}\n")
        print(f"{'因子':<20} {'RankIC均值':<12} {'ICIR':<10} {'IC正比例':<10} {'单调性':<8} {'判定':<8}")
        print('-' * 70)
        for factor, metrics in report.items():
            icir_val = metrics.get('icir', {}).get('icir', 0)
            print(f"{factor:<20} {metrics['ic_mean']:<12.4f} {icir_val:<10.3f} "
                  f"{metrics['ic_positive_ratio']:<10.1%} {metrics['monotonicity']:<8} {metrics['verdict']:<8}")


if __name__ == '__main__':
    main()
