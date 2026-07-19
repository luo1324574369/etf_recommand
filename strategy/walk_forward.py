"""Walk-Forward参数优化引擎

使用Anchored Walk-Forward方法验证参数鲁棒性，
生成5个差异化的参数预设。

算法流程:
    1. 分割时间区间为6个月的验证窗口
    2. 对每个参数组合在所有窗口跑回测验证
    3. 计算鲁棒性得分 = 0.7 * 平均夏普 + 0.3 * 最差夏普
    4. 按不同优化目标选出5个差异化预设
    5. 去重: 每个预设的参数组合必须不同
"""
import itertools
import time
from typing import Dict, List, Any, Optional, Callable
import pandas as pd


# 5种预设风格定义
PRESET_STYLES = [
    {
        'key': 'high_return',
        'name': '🏆 激进高收益型',
        'metric': 'full_annual_return',
        'sort_order': 'desc',
        'min_sharpe': 0.3,
    },
    {
        'key': 'best_robustness',
        'name': '🥇 最优风险调整型',
        'metric': 'robustness_score',
        'sort_order': 'desc',
    },
    {
        'key': 'balanced',
        'name': '🥈 均衡稳健型',
        'metric': 'full_sharpe_ratio',
        'sort_order': 'desc',
    },
    {
        'key': 'low_drawdown',
        'name': '🥉 最低回撤型',
        'metric': 'full_max_drawdown',
        'sort_order': 'asc',
        'min_return': 0,
    },
    {
        'key': 'low_turnover',
        'name': '📊 低频交易型',
        'metric': 'full_num_trades',
        'sort_order': 'asc',
        'min_return': 0,
    },
]


def split_windows(start_date: str, end_date: str, val_months: int = 6) -> List[Dict[str, Optional[str]]]:
    """将时间区间按指定月数分割为验证窗口

    Anchored Walk-Forward: 训练期起点固定为数据最早日期，
    验证期按val_months滑动。

    Args:
        start_date: 回测起始日期 'YYYY-MM-DD'
        end_date: 回测结束日期 'YYYY-MM-DD'
        val_months: 每个验证窗口的月数，默认6

    Returns:
        窗口列表，每个包含:
            - train_start: None (运行时由数据决定)
            - train_end: 训练期结束=验证期起点
            - val_start: 验证期起点
            - val_end: 验证期终点
    """
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    windows = []
    val_start = start_dt
    while val_start < end_dt:
        val_end = val_start + pd.DateOffset(months=val_months)
        if val_end > end_dt:
            val_end = end_dt
        if val_end <= val_start:
            break
        windows.append({
            'train_start': None,  # 训练起点是数据最早日期，运行时确定
            'train_end': val_start.strftime('%Y-%m-%d'),
            'val_start': val_start.strftime('%Y-%m-%d'),
            'val_end': val_end.strftime('%Y-%m-%d'),
        })
        val_start = val_end

    return windows


def calculate_robustness_score(sharpes: List[float]) -> float:
    """计算鲁棒性得分 = 0.7 * 平均夏普 + 0.3 * 最差夏普

    平均夏普反映整体表现，最差夏普反映极端情况下的稳定性，
    加权组合既鼓励高收益又惩罚大幅回撤。

    Args:
        sharpes: 各验证窗口的夏普比率列表

    Returns:
        鲁棒性得分，列表为空时返回0.0
    """
    if not sharpes:
        return 0.0
    avg = sum(sharpes) / len(sharpes)
    worst = min(sharpes)
    return 0.7 * avg + 0.3 * worst


def _run_single_backtest(strategy_module, data_dict: Dict[str, pd.DataFrame],
                         params: Dict[str, Any], start_date: str, end_date: str,
                         extra_params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, float]]:
    """运行单次回测，返回关键指标

    Args:
        strategy_module: 策略模块（如 dual_momentum, multi_factor）
        data_dict: ETF行情数据
        params: 策略参数字典
        start_date: 回测起始日期
        end_date: 回测结束日期
        extra_params: 额外回测参数（如 valuation_repo），会合并到 params 中

    Returns:
        包含 annual_return, sharpe_ratio, max_drawdown, num_trades, total_return 的字典，
        回测失败时返回None
    """
    try:
        full_params = {**params}
        if extra_params:
            full_params.update(extra_params)
        result = strategy_module.run_backtest(
            data_dict,
            initial_capital=1000000,
            start_date=start_date,
            end_date=end_date,
            **full_params,
        )
        total_return = result.get('total_return', None)
        if total_return is None:
            annual = result.get('annual_return', 0) or 0
            days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
            if days > 0:
                total_return = (1 + annual / 100) ** (days / 252) - 1
                total_return = total_return * 100
            else:
                total_return = 0
        return {
            'annual_return': result.get('annual_return', 0) or 0,
            'sharpe_ratio': result.get('sharpe_ratio', 0) or 0,
            'max_drawdown': result.get('max_drawdown', 0) or 0,
            'num_trades': result.get('num_trades', 0) or 0,
            'total_return': total_return,
        }
    except Exception:
        return None


def _cagr_from_returns(total_returns_pct: List[float]) -> float:
    """从多段收益率计算复合年化增长率(CAGR)

    Args:
        total_returns_pct: 各段总收益率列表(%)

    Returns:
        复合年化收益率(%)
    """
    if not total_returns_pct:
        return 0.0
    cumulative = 1.0
    for r in total_returns_pct:
        cumulative *= (1 + r / 100)
    return (cumulative - 1) * 100


def generate_walk_forward_presets(
    data_dict: Dict[str, pd.DataFrame],
    start_date: str,
    end_date: str,
    param_ranges: Dict[str, List[Any]],
    max_combinations: int = 144,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    strategy_module=None,
    extra_params: Optional[Dict[str, Any]] = None,
    min_full_annual_return: Optional[float] = None,
) -> Dict[str, Any]:
    """生成Walk-Forward参数预设

    对每个参数组合在所有验证窗口跑回测，计算各指标平均值和鲁棒性得分，
    按不同优化目标选出5个差异化预设。

    Args:
        data_dict: ETF行情数据 {code: DataFrame}
        start_date: 回测起始日期 'YYYY-MM-DD'
        end_date: 回测结束日期 'YYYY-MM-DD'
        param_ranges: 参数范围字典，如 {'top_n': [1,2,3], 'rebalance_freq': [20,60]}
        max_combinations: 最大参数组合数限制，默认144
        progress_callback: 进度回调函数 (current, total, message)
        strategy_module: 策略模块（需有 run_backtest 函数），默认 None 时使用 dual_momentum
        extra_params: 额外回测参数（如 valuation_repo），会合并到每次回测的参数中
        min_full_annual_return: 全周期年化收益下限(%)，用于筛选预设（如跑赢基准）。
            None 时不筛选。若筛选后组合数不足5个，回退到不筛选。

    Returns:
        {
            'presets': [
                {
                    'key': 预设标识,
                    'name': 预设名称,
                    'params': 参数字典,
                    'metrics': {
                        'avg_annual_return': 平均年化收益,
                        'avg_sharpe_ratio': 平均夏普,
                        'avg_max_drawdown': 平均最大回撤,
                        'avg_num_trades': 平均交易次数,
                        'robustness_score': 鲁棒性得分,
                        'worst_sharpe': 最差夏普,
                        'validation_windows': 验证窗口数,
                    }
                },
                ... # 共5个
            ],
            'windows': 窗口信息列表,
            'total_combinations': 总参数组合数,
            'elapsed_time': 耗时(秒),
        }
    """
    if strategy_module is None:
        from strategy import dual_momentum as strategy_module

    start_time = time.time()

    # 1. 分割验证窗口
    windows = split_windows(start_date, end_date, val_months=6)
    if len(windows) < 3:
        # 数据不足3个窗口，使用全量数据做单次优化
        windows = [{
            'train_start': None,
            'train_end': start_date,
            'val_start': start_date,
            'val_end': end_date,
        }]

    # 2. 生成参数组合
    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]
    all_combinations = list(itertools.product(*param_values))
    if len(all_combinations) > max_combinations:
        all_combinations = all_combinations[:max_combinations]

    total_steps = len(all_combinations) * (len(windows) + 1)
    current_step = 0

    # 3. 对每个参数组合在所有窗口验证 + 全周期回测
    all_results = []
    for combo in all_combinations:
        params = dict(zip(param_names, combo))
        window_results = []

        # 跑所有验证窗口
        for w in windows:
            if progress_callback:
                current_step += 1
                progress_callback(
                    current_step, total_steps,
                    f"验证参数: {params} | 窗口: {w['val_start']}~{w['val_end']}",
                )

            metrics = _run_single_backtest(
                strategy_module, data_dict, params,
                w['val_start'], w['val_end'],
                extra_params=extra_params,
            )
            if metrics is not None:
                window_results.append(metrics)

        # 跑全周期回测
        if progress_callback:
            current_step += 1
            progress_callback(
                current_step, total_steps,
                f"全周期回测: {params}",
            )

        full_metrics = _run_single_backtest(
            strategy_module, data_dict, params,
            start_date, end_date,
            extra_params=extra_params,
        )

        if not window_results and full_metrics is None:
            continue

        # 窗口指标
        if window_results:
            avg_sharpe = sum(r['sharpe_ratio'] for r in window_results) / len(window_results)
            avg_drawdown = sum(r['max_drawdown'] for r in window_results) / len(window_results)
            avg_trades = sum(r['num_trades'] for r in window_results) / len(window_results)
            sharpes = [r['sharpe_ratio'] for r in window_results]
            robustness = calculate_robustness_score(sharpes)
            worst_sharpe = min(sharpes) if sharpes else 0
            # 用各窗口总收益率计算CAGR
            window_total_returns = [r['total_return'] for r in window_results]
            window_cagr = _cagr_from_returns(window_total_returns)
        else:
            avg_sharpe = 0
            avg_drawdown = 0
            avg_trades = 0
            robustness = 0
            worst_sharpe = 0
            window_cagr = 0

        # 全周期指标
        if full_metrics is not None:
            full_annual = full_metrics['annual_return']
            full_sharpe = full_metrics['sharpe_ratio']
            full_drawdown = full_metrics['max_drawdown']
            full_trades = full_metrics['num_trades']
        else:
            full_annual = 0
            full_sharpe = 0
            full_drawdown = 0
            full_trades = 0

        all_results.append({
            'params': params.copy(),
            'param_str': str(params),
            'metrics': {
                'cagr': window_cagr,
                'avg_sharpe_ratio': avg_sharpe,
                'avg_max_drawdown': avg_drawdown,
                'avg_num_trades': avg_trades,
                'robustness_score': robustness,
                'worst_sharpe': worst_sharpe,
                'validation_windows': len(window_results),
                'full_annual_return': full_annual,
                'full_sharpe_ratio': full_sharpe,
                'full_max_drawdown': full_drawdown,
                'full_num_trades': full_trades,
            },
        })

    elapsed_time = time.time() - start_time

    if not all_results:
        return {
            'presets': [],
            'windows': windows,
            'total_combinations': len(all_combinations),
            'elapsed_time': elapsed_time,
        }

    # 4. 按不同风格选出5个差异化预设（去重）
    # 基准收益筛选：若设置了 min_full_annual_return，先过滤掉未跑赢基准的组合
    benchmark_filtered_results = all_results
    benchmark_applied = False
    if min_full_annual_return is not None:
        benchmark_filtered_results = [
            r for r in all_results
            if r['metrics'].get('full_annual_return', 0) > min_full_annual_return
        ]
        benchmark_applied = True
        if len(benchmark_filtered_results) < 5:
            # 筛选后组合数不足5个，回退到不筛选
            benchmark_filtered_results = all_results
            benchmark_applied = False

    used_param_strs = set()
    presets = []

    for style in PRESET_STYLES:
        metric = style['metric']
        sort_order = style['sort_order']

        # 按当前风格的指标排序
        sorted_results = sorted(
            benchmark_filtered_results,
            key=lambda x: x['metrics'].get(metric, float('-inf')),
            reverse=(sort_order == 'desc'),
        )

        # 应用筛选条件
        filtered = sorted_results
        if style.get('min_sharpe') is not None:
            min_s = style['min_sharpe']
            filtered = [r for r in filtered
                       if r['metrics'].get('full_sharpe_ratio', 0) >= min_s]
            if not filtered:
                filtered = sorted_results
        if style.get('min_return') is not None:
            min_r = style['min_return']
            filtered = [r for r in filtered
                       if r['metrics'].get('full_annual_return', 0) > min_r]
            if not filtered:
                filtered = sorted_results

        # 选择未被使用过的最优组合
        for result in filtered:
            param_str = result['param_str']
            if param_str in used_param_strs:
                continue
            used_param_strs.add(param_str)
            presets.append({
                'key': style['key'],
                'name': style['name'],
                'params': result['params'].copy(),
                'metrics': result['metrics'].copy(),
            })
            break

        if len(presets) >= 5:
            break

    return {
        'presets': presets,
        'windows': windows,
        'total_combinations': len(all_combinations),
        'elapsed_time': elapsed_time,
        'benchmark_applied': benchmark_applied,
        'benchmark_threshold': min_full_annual_return,
        'all_results_count': len(all_results),
        'benchmark_filtered_count': len(benchmark_filtered_results),
    }
