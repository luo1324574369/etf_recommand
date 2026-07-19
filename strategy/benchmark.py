"""
基准净值计算模块
支持单ETF基准（默认：沪深300）
"""
import pandas as pd
from typing import Dict, List, Any


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
    {'name': '沪深300', 'type': 'single_etf', 'code': '510300'},
]

# 主基准常量：所有 summary 字段、UI 默认引用此常量
PRIMARY_BENCHMARK = '沪深300'


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

        if btype == 'single_etf':
            nav_df = build_single_etf_benchmark(
                data_dict, config['code'], start_date, end_date
            )
        else:
            nav_df = pd.DataFrame(columns=['date', 'nav'])

        if not nav_df.empty:
            result[name] = nav_df

    return result
