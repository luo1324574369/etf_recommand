"""Brinson 归因模块

将策略相对基准的超额收益拆解为配置效应 + 选股效应 + 交互效应。

公式（单期 Brinson-Fachler）：
    BA_i = (w_p_i - w_b_i) * (r_b_i - r_b)         # 配置效应
    BS_i = w_b_i * (r_p_i - r_b_i)                  # 选股效应
    BI_i = (w_p_i - w_b_i) * (r_p_i - r_b_i)        # 交互效应

多期累加采用算术平均（简化处理，不使用 log-link）。
"""
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd


@dataclass
class BrinsonResult:
    """Brinson 归因结果"""
    allocation_effect: float           # 配置效应(%)
    selection_effect: float            # 选股效应(%)
    interaction_effect: float         # 交互效应(%)
    total_excess: float                # 总超额(%)
    sector_breakdown: pd.DataFrame     # 分行业明细
    period_breakdown: pd.DataFrame     # 分调仓期间明细


def _calc_single_period(
    strategy_weights: Dict[str, float],
    benchmark_weights: Dict[str, float],
    strategy_returns: Dict[str, float],
    benchmark_returns: Dict[str, float],
    benchmark_total_return: float,
) -> Dict:
    """计算单期 Brinson 归因

    Args:
        strategy_weights: {行业: 权重(0~1)}
        benchmark_weights: {行业: 权重(0~1)}
        strategy_returns: {行业: 收益率(0~1)}
        benchmark_returns: {行业: 收益率(0~1)}
        benchmark_total_return: 基准整体收益率(0~1)

    Returns:
        {
            'allocation_effect': float,
            'selection_effect': float,
            'interaction_effect': float,
            'total_excess': float,
            'sector_detail': pd.DataFrame,
        }
    """
    all_sectors = set(strategy_weights.keys()) | set(benchmark_weights.keys())

    rows = []
    total_ba = total_bs = total_bi = 0.0

    for sector in all_sectors:
        w_p = strategy_weights.get(sector, 0.0)
        w_b = benchmark_weights.get(sector, 0.0)
        r_p = strategy_returns.get(sector, 0.0)
        r_b = benchmark_returns.get(sector, 0.0)

        ba = (w_p - w_b) * (r_b - benchmark_total_return)
        bs = w_b * (r_p - r_b)
        bi = (w_p - w_b) * (r_p - r_b)

        total_ba += ba
        total_bs += bs
        total_bi += bi

        rows.append({
            '行业': sector,
            '策略权重': w_p,
            '基准权重': w_b,
            '策略收益率': r_p,
            '基准收益率': r_b,
            '配置效应': ba,
            '选股效应': bs,
            '交互效应': bi,
        })

    return {
        'allocation_effect': total_ba,
        'selection_effect': total_bs,
        'interaction_effect': total_bi,
        'total_excess': total_ba + total_bs + total_bi,
        'sector_detail': pd.DataFrame(rows),
    }


def run_brinson_attribution(
    trade_log: List[Dict],
    strategy_nav: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    csi300_source,
    etf_sector_map: Dict[str, str],
    start_date: str,
    end_date: str,
    rebalance_dates: List[str] = None,
) -> BrinsonResult:
    """运行 Brinson 归因分析

    Args:
        trade_log: 策略交易记录，每条至少包含
                   {date(YYYY-MM-DD), code, direction('买入'/'卖出'), amount}
        strategy_nav: 策略净值 DataFrame[date, nav]
        benchmark_nav: 基准净值 DataFrame[date, nav]
        csi300_source: CSI300Source 实例（需实现 get_industry_weights(date)）
        etf_sector_map: {ETF code: 申万一级行业}，未映射的 ETF 应映射为 '未归类'
        start_date: 起始日 YYYY-MM-DD
        end_date: 结束日 YYYY-MM-DD
        rebalance_dates: 调仓日列表（YYYY-MM-DD），若 None 则从 trade_log 推断

    Returns:
        BrinsonResult（效应字段已转为百分比，例如 1.0 = 1%）

    Raises:
        RuntimeError: 任一调仓日沪深300成分股数据获取失败
    """
    if rebalance_dates is None:
        rebalance_dates = _extract_rebalance_dates(trade_log)

    if not rebalance_dates:
        return BrinsonResult(
            allocation_effect=0.0,
            selection_effect=0.0,
            interaction_effect=0.0,
            total_excess=0.0,
            sector_breakdown=pd.DataFrame(),
            period_breakdown=pd.DataFrame(),
        )

    # 按调仓期间切分：[start, rebalance_1, rebalance_2, ..., end]
    all_dates = [start_date] + rebalance_dates + [end_date]
    period_results = []

    for i in range(len(all_dates) - 1):
        period_start = all_dates[i]
        period_end = all_dates[i + 1]

        # 期初策略持仓权重（按行业聚合）
        strategy_weights = _get_strategy_weights_at(
            trade_log, etf_sector_map, period_start
        )

        # 期初沪深300行业权重（严格模式：失败抛 RuntimeError）
        try:
            date_yyyymmdd = (
                period_start.replace('-', '') if '-' in period_start else period_start
            )
            benchmark_industry_weights = csi300_source.get_industry_weights(date_yyyymmdd)
        except RuntimeError as e:
            raise RuntimeError(
                f"Brinson 归因数据不完整: 调仓日 {period_start} 成分股获取失败. "
                f"原始错误: {e}"
            ) from e

        # 期间策略各行业收益率
        strategy_returns = _get_strategy_returns(
            trade_log, etf_sector_map, strategy_nav, period_start, period_end
        )

        # 期间基准收益率
        # 简化处理：用基准整体收益率替代单行业收益率（数据源限制）
        benchmark_total_return = _get_period_return(benchmark_nav, period_start, period_end)
        benchmark_returns = {
            sec: benchmark_total_return for sec in benchmark_industry_weights
        }

        period_result = _calc_single_period(
            strategy_weights=strategy_weights,
            benchmark_weights=benchmark_industry_weights,
            strategy_returns=strategy_returns,
            benchmark_returns=benchmark_returns,
            benchmark_total_return=benchmark_total_return,
        )
        period_result['period_start'] = period_start
        period_result['period_end'] = period_end
        period_results.append(period_result)

    # 多期累加（算术平均，不按期间长度加权）
    total_ba = sum(p['allocation_effect'] for p in period_results)
    total_bs = sum(p['selection_effect'] for p in period_results)
    total_bi = sum(p['interaction_effect'] for p in period_results)

    return BrinsonResult(
        allocation_effect=total_ba * 100,
        selection_effect=total_bs * 100,
        interaction_effect=total_bi * 100,
        total_excess=(total_ba + total_bs + total_bi) * 100,
        sector_breakdown=_aggregate_sector_breakdown(period_results),
        period_breakdown=pd.DataFrame([
            {
                '期间起始': p['period_start'],
                '期间结束': p['period_end'],
                '配置效应(%)': p['allocation_effect'] * 100,
                '选股效应(%)': p['selection_effect'] * 100,
                '交互效应(%)': p['interaction_effect'] * 100,
                '总效应(%)': p['total_excess'] * 100,
            }
            for p in period_results
        ]),
    )


def _extract_rebalance_dates(trade_log: List[Dict]) -> List[str]:
    """从交易日志提取调仓日（去重、升序）"""
    if not trade_log:
        return []
    return sorted(set(t['date'] for t in trade_log))


def _get_strategy_weights_at(
    trade_log: List[Dict],
    etf_sector_map: Dict[str, str],
    date: str,
) -> Dict[str, float]:
    """获取指定日期的策略行业权重

    简化实现：累计该日（含）之前的所有买入-卖出，按行业聚合市值。
    未归类行业（宽基/红利/海外）的权重不计入（无对应基准行业）。
    """
    sector_value = {}
    total_value = 0.0
    for trade in trade_log:
        if trade['date'] > date:
            continue
        code = trade['code']
        sector = etf_sector_map.get(code, '未归类')
        if sector == '未归类':
            # 宽基/红利/海外 ETF 跨行业，无法与基准单行业对齐
            continue
        amount = trade['amount']
        if trade['direction'] == '买入':
            sector_value[sector] = sector_value.get(sector, 0) + amount
            total_value += amount
        else:  # 卖出
            sector_value[sector] = sector_value.get(sector, 0) - amount
            total_value -= amount

    if total_value <= 0:
        return {}
    return {sec: max(v, 0) / total_value for sec, v in sector_value.items() if v > 0}


def _get_strategy_returns(
    trade_log: List[Dict],
    etf_sector_map: Dict[str, str],
    strategy_nav: pd.DataFrame,
    start: str,
    end: str,
) -> Dict[str, float]:
    """获取期间策略各行业收益率（简化：用策略整体收益率）"""
    period_return = _get_period_return(strategy_nav, start, end)
    sector_weights = _get_strategy_weights_at(trade_log, etf_sector_map, start)
    return {sec: period_return for sec in sector_weights}


def _get_period_return(nav_df: pd.DataFrame, start: str, end: str) -> float:
    """计算区间的整体收益率"""
    if nav_df is None or nav_df.empty:
        return 0.0
    nav_df = nav_df.copy()
    nav_df['date'] = pd.to_datetime(nav_df['date'])
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    mask = (nav_df['date'] >= start_dt) & (nav_df['date'] <= end_dt)
    period = nav_df[mask]
    if len(period) < 2:
        return 0.0
    first_nav = period.iloc[0]['nav']
    last_nav = period.iloc[-1]['nav']
    if first_nav <= 0:
        return 0.0
    return (last_nav / first_nav - 1)


def _aggregate_sector_breakdown(period_results: List[Dict]) -> pd.DataFrame:
    """聚合多期分行业明细"""
    if not period_results:
        return pd.DataFrame()
    dfs = [p['sector_detail'] for p in period_results if not p['sector_detail'].empty]
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    agg = combined.groupby('行业').agg({
        '配置效应': 'sum',
        '选股效应': 'sum',
        '交互效应': 'sum',
    }).reset_index()
    agg['配置效应(%)'] = agg['配置效应'] * 100
    agg['选股效应(%)'] = agg['选股效应'] * 100
    agg['交互效应(%)'] = agg['交互效应'] * 100
    agg['总效应(%)'] = (agg['配置效应'] + agg['选股效应'] + agg['交互效应']) * 100
    return agg[['行业', '配置效应(%)', '选股效应(%)', '交互效应(%)', '总效应(%)']]
