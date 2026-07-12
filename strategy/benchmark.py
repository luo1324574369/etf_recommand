"""
基准净值计算模块
支持等权买入持有基准和单ETF基准
"""
import pandas as pd
from typing import Dict, List, Any


def build_equal_weight_benchmark(
    data_dict: Dict[str, pd.DataFrame],
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """构建等权买入持有基准净值

    每日收益率 = 所有已有数据ETF的日收益率等权平均，复利计算，首日净值=1.0
    上市前不参与当日平均。

    Args:
        data_dict: {code: DataFrame}，每个DataFrame含 trade_date, close 列
        start_date: 起始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）

    Returns:
        DataFrame[date, nav]，date为datetime，nav从1.0开始
    """
    if not data_dict:
        return pd.DataFrame(columns=['date', 'nav'])

    etf_daily_returns = {}
    all_dates = set()

    for code, df in data_dict.items():
        df_copy = df.copy()
        if start_date:
            df_copy = df_copy[df_copy['trade_date'] >= start_date]
        if end_date:
            df_copy = df_copy[df_copy['trade_date'] <= end_date]
        df_copy = df_copy.sort_values('trade_date').drop_duplicates('trade_date')
        if len(df_copy) >= 2:
            df_copy['daily_return'] = df_copy['close'].pct_change()
            etf_daily_returns[code] = df_copy[['trade_date', 'daily_return']]
            all_dates.update(df_copy['trade_date'].tolist())

    if not etf_daily_returns or not all_dates:
        return pd.DataFrame(columns=['date', 'nav'])

    all_dates_sorted = sorted(all_dates)
    merged = pd.DataFrame({'trade_date': all_dates_sorted})

    for code, df_ret in etf_daily_returns.items():
        merged = merged.merge(
            df_ret.rename(columns={'daily_return': code}),
            on='trade_date',
            how='left',
        )

    merged = merged.sort_values('trade_date').reset_index(drop=True)
    code_cols = [c for c in merged.columns if c != 'trade_date']
    merged['avg_daily_return'] = merged[code_cols].mean(axis=1)

    nav_list = []
    nav = 1.0
    for idx, row in merged.iterrows():
        if idx == 0:
            nav_list.append({
                'date': pd.to_datetime(row['trade_date']),
                'nav': 1.0,
            })
        else:
            ret = row['avg_daily_return']
            if pd.notna(ret):
                nav *= (1 + ret)
            nav_list.append({
                'date': pd.to_datetime(row['trade_date']),
                'nav': nav,
            })

    return pd.DataFrame(nav_list)


def build_single_etf_benchmark(
    data_dict: Dict[str, pd.DataFrame],
    etf_code: str,
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """构建单ETF基准净值

    首日归一化为1.0。若ETF不在数据池中，返回空DataFrame。

    Args:
        data_dict: {code: DataFrame}
        etf_code: ETF代码
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        DataFrame[date, nav]，date为datetime，nav从1.0开始
    """
    if etf_code not in data_dict:
        return pd.DataFrame(columns=['date', 'nav'])

    df = data_dict[etf_code].copy()
    if start_date:
        df = df[df['trade_date'] >= start_date]
    if end_date:
        df = df[df['trade_date'] <= end_date]
    df = df.sort_values('trade_date').drop_duplicates('trade_date')

    if len(df) < 2:
        return pd.DataFrame(columns=['date', 'nav'])

    first_close = df.iloc[0]['close']
    df['nav'] = df['close'] / first_close
    df['date'] = pd.to_datetime(df['trade_date'])

    return df[['date', 'nav']].reset_index(drop=True)


# 默认基准配置
DEFAULT_BENCHMARKS = [
    {'name': '等权持有', 'type': 'equal_weight'},
    {'name': '沪深300', 'type': 'single_etf', 'code': '510300'},
    {'name': '中证500', 'type': 'single_etf', 'code': '510500'},
    {'name': '创业板', 'type': 'single_etf', 'code': '159915'},
]


def build_benchmarks(
    data_dict: Dict[str, pd.DataFrame],
    benchmark_configs: List[Dict[str, Any]] = None,
    start_date: str = None,
    end_date: str = None,
) -> Dict[str, pd.DataFrame]:
    """一次性构建多个基准

    Args:
        data_dict: {code: DataFrame}
        benchmark_configs: 基准配置列表，默认使用DEFAULT_BENCHMARKS
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        {基准名称: 净值DataFrame}
    """
    if benchmark_configs is None:
        benchmark_configs = DEFAULT_BENCHMARKS

    result = {}
    for config in benchmark_configs:
        name = config['name']
        btype = config['type']

        if btype == 'equal_weight':
            nav_df = build_equal_weight_benchmark(data_dict, start_date, end_date)
        elif btype == 'single_etf':
            nav_df = build_single_etf_benchmark(
                data_dict, config['code'], start_date, end_date
            )
        else:
            nav_df = pd.DataFrame(columns=['date', 'nav'])

        if not nav_df.empty:
            result[name] = nav_df

    return result
