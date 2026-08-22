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
class AttributionResult:
    """归因结果（双体系：BF归因 + 换仓/持有拆解）"""
    # BF 归因（双分项）
    allocation_effect: float           # 配置收益(%)
    selection_effect: float            # 选品收益(%)
    total_excess: float                # 总超额(%)
    sector_breakdown: pd.DataFrame     # 分赛道明细
    period_breakdown: pd.DataFrame     # 分调仓期间明细
    
    # 换仓/持有拆解
    hold_return: float                 # 持有收益(%)
    switch_return: float               # 换仓收益(%)
    switch_win_rate: float             # 换仓胜率
    rolling_ir: float                  # 滚动IR
    etf_switch_breakdown: pd.DataFrame # 分ETF换仓明细
    switch_period_breakdown: pd.DataFrame # 分期间换仓明细
    
    # 元信息
    benchmark_type: str                # 基准类型: 'equal_weight' / 'csi300'
    total_periods: int                 # 总期数
    benchmark_fallback_reason: str | None = None


def compute_equal_weight_benchmark(
    etf_codes: List[str],
    valuation_repo,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """计算ETF池等权基准净值

    每日等权再平衡（简化：用价格等权近似）。

    Args:
        etf_codes: ETF代码列表
        valuation_repo: 估值数据源（需实现 get_daily_price(code) -> List[Dict]）
        start_date: 起始日 YYYY-MM-DD
        end_date: 结束日 YYYY-MM-DD

    Returns:
        DataFrame[date, nav]，date为字符串 YYYY-MM-DD
    """
    if not etf_codes:
        return pd.DataFrame(columns=['date', 'nav'])

    all_prices = {}
    for code in etf_codes:
        records = valuation_repo.get_daily_price(code)
        if not records:
            continue
        df = pd.DataFrame(records)
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
        df = df.set_index('trade_date')['close'].sort_index()
        df = df.loc[start_date:end_date]
        if not df.empty:
            all_prices[code] = df

    if not all_prices:
        return pd.DataFrame(columns=['date', 'nav'])

    price_df = pd.DataFrame(all_prices).ffill()
    returns = price_df.pct_change().fillna(0)
    equal_weight_return = returns.mean(axis=1)
    nav = (1 + equal_weight_return).cumprod()

    result = pd.DataFrame({
        'date': nav.index,
        'nav': nav.values,
    })
    return result


def compute_csi300_benchmark(csi300_source, start_date: str, end_date: str) -> pd.DataFrame:
    """构建 CSI300 净值，数据缺失时严格失败。"""
    if csi300_source is None or not hasattr(csi300_source, 'fetch_index_prices'):
        raise RuntimeError("CSI300 基准缺少历史指数价格接口")
    prices = csi300_source.fetch_index_prices(start_date, end_date)
    if prices is None or prices.empty:
        raise RuntimeError("CSI300 基准历史指数价格为空")
    required = {'date', 'close'}
    if not required.issubset(prices.columns):
        raise RuntimeError("CSI300 基准历史价格缺少 date/close 字段")
    benchmark = prices[['date', 'close']].copy()
    benchmark['date'] = pd.to_datetime(benchmark['date']).dt.strftime('%Y-%m-%d')
    benchmark['close'] = pd.to_numeric(benchmark['close'], errors='coerce')
    benchmark = benchmark.dropna().sort_values('date')
    if benchmark.empty or (benchmark['close'] <= 0).any():
        raise RuntimeError("CSI300 基准历史价格无有效收盘价")
    benchmark['nav'] = benchmark['close'] / benchmark['close'].iloc[0]
    return benchmark[['date', 'nav']].reset_index(drop=True)


def _compute_csi300_sector_weights(csi300_source, date: str) -> Dict[str, float]:
    if not hasattr(csi300_source, 'fetch_constituents'):
        raise RuntimeError("CSI300 基准缺少历史成分接口")
    snapshot = csi300_source.fetch_constituents(str(date).replace('-', ''))
    if snapshot is None or snapshot.empty:
        raise RuntimeError(f"CSI300 历史成分为空: {date}")
    if not {'weight', 'sw_industry'}.issubset(snapshot.columns):
        raise RuntimeError("CSI300 历史成分缺少 weight/sw_industry 字段")
    snapshot = snapshot.dropna(subset=['weight', 'sw_industry'])
    if snapshot.empty:
        raise RuntimeError(f"CSI300 历史行业权重为空: {date}")
    weights = snapshot.groupby('sw_industry')['weight'].sum()
    total = float(weights.sum())
    if total <= 0:
        raise RuntimeError(f"CSI300 历史行业权重无效: {date}")
    return {str(sector): float(weight / total) for sector, weight in weights.items()}


def _compute_csi300_sector_returns(csi300_source, start_date: str, end_date: str) -> Dict[str, float]:
    method = getattr(csi300_source, 'fetch_sector_returns', None)
    if method is None:
        raise RuntimeError(
            "CSI300 基准缺少历史行业收益接口，禁止用 ETF 赛道收益替代"
        )
    returns = method(start_date, end_date)
    if not returns:
        raise RuntimeError(f"CSI300 历史行业收益为空: {start_date} ~ {end_date}")
    return {str(sector): float(value) for sector, value in returns.items()}


def _calc_single_period_bf(
    strategy_weights: Dict[str, float],
    benchmark_weights: Dict[str, float],
    etf_returns: Dict[str, float],
    sector_returns: Dict[str, float],
    etf_to_sector: Dict[str, str],
    benchmark_total_return: float,
) -> Dict:
    """计算单期 BF 双分项归因（配置收益 + 选品收益）

    Args:
        strategy_weights: {ETF code: 权重(0~1)}
        benchmark_weights: {赛道名: 权重(0~1)}
        etf_returns: {ETF code: 收益率(0~1)}
        sector_returns: {赛道名: 收益率(0~1)}
        etf_to_sector: {ETF code: 赛道名}
        benchmark_total_return: 基准整体收益率(0~1)

    Returns:
        {
            'allocation_effect': float,       # 配置收益
            'selection_effect': float,        # 选品收益
            'total_excess': float,            # 总超额
            'sector_detail': pd.DataFrame,    # 分赛道明细
            'etf_detail': pd.DataFrame,       # 分ETF明细
        }
    """
    strategy_sector_weights = {}
    for etf_code, w in strategy_weights.items():
        sector = etf_to_sector.get(etf_code, '未归类')
        strategy_sector_weights[sector] = strategy_sector_weights.get(sector, 0.0) + w

    all_sectors = set(strategy_sector_weights.keys()) | set(benchmark_weights.keys())

    sector_rows = []
    total_allocation = 0.0
    total_selection = 0.0

    for sector in all_sectors:
        w_p = strategy_sector_weights.get(sector, 0.0)
        w_b = benchmark_weights.get(sector, 0.0)
        r_b = sector_returns.get(sector, 0.0)

        allocation_eff = (w_p - w_b) * (r_b - benchmark_total_return)
        total_allocation += allocation_eff

        sector_rows.append({
            '赛道': sector,
            '策略权重': w_p,
            '基准权重': w_b,
            '赛道收益率': r_b,
            '配置收益': allocation_eff,
        })

    etf_rows = []
    for etf_code, w_p in strategy_weights.items():
        r_p = etf_returns.get(etf_code, 0.0)
        sector = etf_to_sector.get(etf_code, '未归类')
        r_b = sector_returns.get(sector, 0.0)

        selection_eff = w_p * (r_p - r_b)
        total_selection += selection_eff

        etf_rows.append({
            'ETF': etf_code,
            '赛道': sector,
            '策略权重': w_p,
            'ETF收益率': r_p,
            '赛道收益率': r_b,
            '选品收益': selection_eff,
        })

    return {
        'allocation_effect': total_allocation,
        'selection_effect': total_selection,
        'total_excess': total_allocation + total_selection,
        'sector_detail': pd.DataFrame(sector_rows),
        'etf_detail': pd.DataFrame(etf_rows),
    }


def _calc_switch_hold(
    prev_weights: Dict[str, float],
    curr_weights: Dict[str, float],
    etf_returns: Dict[str, float],
) -> Dict:
    """计算单期换仓/持有收益拆解

    Args:
        prev_weights: 上期ETF权重 {ETF code: 权重(0~1)}
        curr_weights: 本期ETF权重 {ETF code: 权重(0~1)}
        etf_returns: 本期ETF收益率 {ETF code: 收益率(0~1)}

    Returns:
        {
            'hold_return': float,         # 持有收益
            'switch_return': float,       # 换仓收益
            'total_return': float,        # 总收益
            'etf_detail': pd.DataFrame,   # 分ETF明细
        }
    """
    all_etfs = set(prev_weights.keys()) | set(curr_weights.keys())

    etf_rows = []
    total_hold = 0.0
    total_switch = 0.0

    for etf_code in all_etfs:
        w_prev = prev_weights.get(etf_code, 0.0)
        w_curr = curr_weights.get(etf_code, 0.0)
        r = etf_returns.get(etf_code, 0.0)

        hold = w_prev * r
        switch = (w_curr - w_prev) * r
        total = w_curr * r

        total_hold += hold
        total_switch += switch

        etf_rows.append({
            'ETF': etf_code,
            '上期权重': w_prev,
            '本期权重': w_curr,
            '权重变化': w_curr - w_prev,
            '本期收益率': r,
            '持有收益': hold,
            '换仓收益': switch,
            '总收益': total,
        })

    return {
        'hold_return': total_hold,
        'switch_return': total_switch,
        'total_return': total_hold + total_switch,
        'etf_detail': pd.DataFrame(etf_rows),
    }


def _get_etf_weights_at(
    trade_log: List[Dict],
    date: str,
) -> Dict[str, float]:
    """获取指定日期的策略ETF权重

    累计该日（含）之前的所有买入-卖出，按ETF聚合市值。
    """
    etf_value = {}
    total_value = 0.0
    for trade in trade_log:
        if trade['date'] > date:
            continue
        code = trade['code']
        amount = trade['amount']
        if trade['direction'] == '买入':
            etf_value[code] = etf_value.get(code, 0) + amount
            total_value += amount
        else:
            etf_value[code] = etf_value.get(code, 0) - amount
            total_value -= amount

    if total_value <= 0:
        return {}
    return {code: max(v, 0) / total_value for code, v in etf_value.items() if v > 0}


def _compute_sector_returns(
    etf_codes: List[str],
    etf_to_sector: Dict[str, str],
    valuation_repo,
    start_date: str,
    end_date: str,
) -> Dict[str, float]:
    """计算期间各赛道收益率（赛道内ETF等权）"""
    sector_etf_returns = {}
    for code in etf_codes:
        records = valuation_repo.get_daily_price(code)
        if not records:
            continue
        df = pd.DataFrame(records)
        df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
        df = df.set_index('trade_date')['close'].sort_index()
        df = df.loc[start_date:end_date]
        if len(df) < 2:
            continue
        period_return = df.iloc[-1] / df.iloc[0] - 1
        sector = etf_to_sector.get(code, '未归类')
        if sector not in sector_etf_returns:
            sector_etf_returns[sector] = []
        sector_etf_returns[sector].append(period_return)

    sector_returns = {}
    for sector, rets in sector_etf_returns.items():
        if rets:
            sector_returns[sector] = sum(rets) / len(rets)
    return sector_returns


def _compute_equal_weight_benchmark_sector_weights(
    etf_codes: List[str],
    etf_to_sector: Dict[str, str],
) -> Dict[str, float]:
    """计算等权基准的赛道权重"""
    sector_count = {}
    for code in etf_codes:
        sector = etf_to_sector.get(code, '未归类')
        sector_count[sector] = sector_count.get(sector, 0) + 1
    total = len(etf_codes)
    return {sec: cnt / total for sec, cnt in sector_count.items()} if total > 0 else {}


def _compute_rolling_ir(
    strategy_nav: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
    window: int = 20,
) -> float:
    """计算滚动IR（信息比率）"""
    if strategy_nav is None or benchmark_nav is None or len(strategy_nav) < window:
        return 0.0

    s_nav = strategy_nav.copy()
    s_nav['date'] = pd.to_datetime(s_nav['date'])
    s_nav = s_nav.set_index('date').sort_index()

    b_nav = benchmark_nav.copy()
    b_nav['date'] = pd.to_datetime(b_nav['date'])
    b_nav = b_nav.set_index('date').sort_index()

    combined = pd.merge(s_nav, b_nav, left_index=True, right_index=True, how='inner',
                        suffixes=('_s', '_b'))
    if len(combined) < window:
        return 0.0

    excess = combined['nav_s'].pct_change() - combined['nav_b'].pct_change()
    excess = excess.dropna()
    if len(excess) < window:
        return 0.0

    rolling_mean = excess.rolling(window=window).mean()
    rolling_std = excess.rolling(window=window).std()
    rolling_ir = rolling_mean / rolling_std.replace(0, float('nan'))
    rolling_ir = rolling_ir.dropna()

    if rolling_ir.empty:
        return 0.0
    return float(rolling_ir.mean())


def run_attribution(
    trade_log: List[Dict],
    strategy_nav: pd.DataFrame,
    etf_codes: List[str],
    valuation_repo,
    etf_to_sector: Dict[str, str],
    start_date: str,
    end_date: str,
    rebalance_dates: List[str] = None,
    benchmark_type: str = 'equal_weight',
    csi300_source=None,
    benchmark_etf_codes: List[str] | None = None,
) -> AttributionResult:
    """运行归因分析（BF双分项 + 换仓/持有拆解）

    Args:
        trade_log: 策略交易记录
        strategy_nav: 策略净值 DataFrame[date, nav]
        etf_codes: ETF池代码列表
        valuation_repo: 估值数据源（需实现 get_daily_price(code)）
        etf_to_sector: {ETF code: 赛道名}
        start_date: 起始日 YYYY-MM-DD
        end_date: 结束日 YYYY-MM-DD
        rebalance_dates: 调仓日列表，若 None 则从 trade_log 推断
        benchmark_type: 基准类型: 'equal_weight' / 'csi300'
        csi300_source: CSI300Source 实例（csi300基准时需要）

    Returns:
        AttributionResult（百分比单位，例如 1.0 = 1%）
    """
    if rebalance_dates is None:
        rebalance_dates = _extract_rebalance_dates(trade_log)

    proxy_codes = list(benchmark_etf_codes or ['510300'])
    effective_benchmark_type = benchmark_type
    benchmark_fallback_reason = None

    if not rebalance_dates:
        return AttributionResult(
            allocation_effect=0.0,
            selection_effect=0.0,
            total_excess=0.0,
            sector_breakdown=pd.DataFrame(),
            period_breakdown=pd.DataFrame(),
            hold_return=0.0,
            switch_return=0.0,
            switch_win_rate=0.0,
            rolling_ir=0.0,
            etf_switch_breakdown=pd.DataFrame(),
            switch_period_breakdown=pd.DataFrame(),
            benchmark_type=benchmark_type,
            total_periods=0,
        )

    if benchmark_type == 'equal_weight':
        benchmark_nav = compute_equal_weight_benchmark(
            etf_codes, valuation_repo, start_date, end_date
        )
    elif benchmark_type == '510300_proxy':
        benchmark_nav = compute_equal_weight_benchmark(
            proxy_codes, valuation_repo, start_date, end_date
        )
        effective_benchmark_type = '510300_proxy'
        if benchmark_nav.empty:
            raise RuntimeError(f"本地代理 {proxy_codes} 无有效历史价格")
    elif benchmark_type == 'csi300':
        csi_error = RuntimeError("CSI300 基准未配置数据源")
        if csi300_source is not None:
            try:
                benchmark_nav = compute_csi300_benchmark(csi300_source, start_date, end_date)
                csi_error = None
            except RuntimeError as error:
                csi_error = error
        if csi_error is not None:
            benchmark_nav = compute_equal_weight_benchmark(
                proxy_codes, valuation_repo, start_date, end_date
            )
            if benchmark_nav.empty:
                raise RuntimeError(
                    f"沪深300基准不可用，且本地代理 {proxy_codes} 无有效历史价格: {csi_error}"
                ) from csi_error
            effective_benchmark_type = '510300_proxy'
            benchmark_fallback_reason = str(csi_error)
    else:
        raise ValueError(f"不支持的基准类型: {benchmark_type}")

    all_dates = [start_date] + rebalance_dates + [end_date]
    bf_period_results = []
    switch_period_results = []
    prev_weights = {}

    for i in range(len(all_dates) - 1):
        period_start = all_dates[i]
        period_end = all_dates[i + 1]

        curr_weights = _get_etf_weights_at(trade_log, period_start)
        if not curr_weights:
            prev_weights = curr_weights
            continue

        if effective_benchmark_type in {'equal_weight', '510300_proxy'}:
            benchmark_pool = etf_codes if effective_benchmark_type == 'equal_weight' else proxy_codes
            benchmark_sector_weights = _compute_equal_weight_benchmark_sector_weights(
                benchmark_pool, etf_to_sector
            )
        else:
            try:
                benchmark_sector_weights = _compute_csi300_sector_weights(
                    csi300_source, period_start
                )
            except RuntimeError as error:
                proxy_result = run_attribution(
                    trade_log=trade_log,
                    strategy_nav=strategy_nav,
                    etf_codes=etf_codes,
                    valuation_repo=valuation_repo,
                    etf_to_sector=etf_to_sector,
                    start_date=start_date,
                    end_date=end_date,
                    rebalance_dates=rebalance_dates,
                    benchmark_type='510300_proxy',
                    benchmark_etf_codes=proxy_codes,
                )
                proxy_result.benchmark_fallback_reason = str(error)
                return proxy_result

        if effective_benchmark_type in {'equal_weight', '510300_proxy'}:
            benchmark_pool = etf_codes if effective_benchmark_type == 'equal_weight' else proxy_codes
            sector_returns = _compute_sector_returns(
                benchmark_pool, etf_to_sector, valuation_repo, period_start, period_end
            )
        else:
            try:
                sector_returns = _compute_csi300_sector_returns(
                    csi300_source, period_start, period_end
                )
            except RuntimeError as error:
                proxy_result = run_attribution(
                    trade_log=trade_log,
                    strategy_nav=strategy_nav,
                    etf_codes=etf_codes,
                    valuation_repo=valuation_repo,
                    etf_to_sector=etf_to_sector,
                    start_date=start_date,
                    end_date=end_date,
                    rebalance_dates=rebalance_dates,
                    benchmark_type='510300_proxy',
                    benchmark_etf_codes=proxy_codes,
                )
                proxy_result.benchmark_fallback_reason = str(error)
                return proxy_result

        etf_returns = {}
        for code in curr_weights.keys():
            records = valuation_repo.get_daily_price(code)
            if not records:
                etf_returns[code] = 0.0
                continue
            df = pd.DataFrame(records)
            df['trade_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y-%m-%d')
            df = df.set_index('trade_date')['close'].sort_index()
            df = df.loc[period_start:period_end]
            if len(df) < 2:
                etf_returns[code] = 0.0
            else:
                etf_returns[code] = df.iloc[-1] / df.iloc[0] - 1

        benchmark_total_return = _get_period_return(benchmark_nav, period_start, period_end)

        bf_result = _calc_single_period_bf(
            strategy_weights=curr_weights,
            benchmark_weights=benchmark_sector_weights,
            etf_returns=etf_returns,
            sector_returns=sector_returns,
            etf_to_sector=etf_to_sector,
            benchmark_total_return=benchmark_total_return,
        )
        bf_result['period_start'] = period_start
        bf_result['period_end'] = period_end
        bf_period_results.append(bf_result)

        if prev_weights:
            switch_result = _calc_switch_hold(
                prev_weights=prev_weights,
                curr_weights=curr_weights,
                etf_returns=etf_returns,
            )
            switch_result['period_start'] = period_start
            switch_result['period_end'] = period_end
            switch_period_results.append(switch_result)

        prev_weights = curr_weights

    total_allocation = sum(p['allocation_effect'] for p in bf_period_results)
    total_selection = sum(p['selection_effect'] for p in bf_period_results)
    total_excess = total_allocation + total_selection

    total_hold = sum(p['hold_return'] for p in switch_period_results)
    total_switch = sum(p['switch_return'] for p in switch_period_results)

    switch_win_count = sum(1 for p in switch_period_results if p['switch_return'] > 0)
    switch_win_rate = switch_win_count / len(switch_period_results) if switch_period_results else 0.0

    rolling_ir = _compute_rolling_ir(strategy_nav, benchmark_nav)

    sector_breakdown = _aggregate_bf_sector_breakdown(bf_period_results)

    period_breakdown = pd.DataFrame([
        {
            '期间起始': p['period_start'],
            '期间结束': p['period_end'],
            '配置收益(%)': p['allocation_effect'] * 100,
            '选品收益(%)': p['selection_effect'] * 100,
            '总超额(%)': p['total_excess'] * 100,
        }
        for p in bf_period_results
    ])

    switch_period_breakdown = pd.DataFrame([
        {
            '期间起始': p['period_start'],
            '期间结束': p['period_end'],
            '持有收益(%)': p['hold_return'] * 100,
            '换仓收益(%)': p['switch_return'] * 100,
            '总收益(%)': p['total_return'] * 100,
        }
        for p in switch_period_results
    ])

    etf_switch_breakdown = _aggregate_switch_etf_breakdown(switch_period_results)

    return AttributionResult(
        allocation_effect=total_allocation * 100,
        selection_effect=total_selection * 100,
        total_excess=total_excess * 100,
        sector_breakdown=sector_breakdown,
        period_breakdown=period_breakdown,
        hold_return=total_hold * 100,
        switch_return=total_switch * 100,
        switch_win_rate=switch_win_rate,
        rolling_ir=rolling_ir,
        etf_switch_breakdown=etf_switch_breakdown,
        switch_period_breakdown=switch_period_breakdown,
        benchmark_type=effective_benchmark_type,
        total_periods=len(bf_period_results),
        benchmark_fallback_reason=benchmark_fallback_reason,
    )


def _aggregate_bf_sector_breakdown(period_results: List[Dict]) -> pd.DataFrame:
    """聚合多期BF归因分赛道明细"""
    if not period_results:
        return pd.DataFrame()
    dfs = [p['sector_detail'] for p in period_results if not p['sector_detail'].empty]
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    agg = combined.groupby('赛道').agg({
        '配置收益': 'sum',
        '策略权重': 'mean',
        '基准权重': 'mean',
    }).reset_index()
    agg['配置收益(%)'] = agg['配置收益'] * 100
    return agg[['赛道', '策略权重', '基准权重', '配置收益(%)']]


def _aggregate_switch_etf_breakdown(period_results: List[Dict]) -> pd.DataFrame:
    """聚合多期换仓拆解分ETF明细"""
    if not period_results:
        return pd.DataFrame()
    dfs = [p['etf_detail'] for p in period_results if not p['etf_detail'].empty]
    if not dfs:
        return pd.DataFrame()
    combined = pd.concat(dfs, ignore_index=True)
    agg = combined.groupby('ETF').agg({
        '持有收益': 'sum',
        '换仓收益': 'sum',
        '总收益': 'sum',
    }).reset_index()
    agg['持有收益(%)'] = agg['持有收益'] * 100
    agg['换仓收益(%)'] = agg['换仓收益'] * 100
    agg['总收益(%)'] = agg['总收益'] * 100
    return agg[['ETF', '持有收益(%)', '换仓收益(%)', '总收益(%)']]


def _extract_rebalance_dates(trade_log: List[Dict]) -> List[str]:
    """从交易日志提取调仓日（去重、升序）"""
    if not trade_log:
        return []
    return sorted(set(t['date'] for t in trade_log))


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
