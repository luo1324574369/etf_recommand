"""Walk-Forward参数优化引擎

使用Anchored Walk-Forward方法验证参数鲁棒性，
生成3-7个差异化的参数预设。

算法流程:
    1. 分割时间区间为6个月的验证窗口
    2. 对每个参数组合在所有窗口跑回测验证（多进程并行）
    3. 计算鲁棒性得分 = 0.7 * 平均夏普 + 0.3 * 最差夏普
    4. 按不同优化目标选出3-7个差异化预设
    5. 去重: 每个预设的参数组合必须不同
"""
import itertools
import os
import time
from typing import Dict, List, Any, Optional, Callable
from multiprocessing import get_context
import pandas as pd


PRESET_STYLES = [
    {
        'key': 'high_return',
        'name': '🏆 收益优先型',
        'metric': 'validation_annual_return',
        'sort_order': 'desc',
        'min_sharpe': 0.3,
    },
    {
        'key': 'balanced',
        'name': '⚖️ 均衡型',
        'metric': 'validation_sharpe_ratio',
        'sort_order': 'desc',
    },
    {
        'key': 'low_drawdown',
        'name': '🛡️ 低回撤型',
        'metric': 'validation_max_drawdown',
        'sort_order': 'asc',
        'min_return_benchmark_ratio': 0.8,
    },
    {
        'key': 'low_turnover',
        'name': '📊 低频交易型',
        'metric': 'validation_num_trades',
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
                         extra_params: Optional[Dict[str, Any]] = None,
                         enable_attribution: bool = False) -> Optional[Dict[str, float]]:
    """运行单次回测，返回关键指标

    Args:
        strategy_module: 策略模块（如 dual_momentum, multi_factor）
        data_dict: ETF行情数据
        params: 策略参数字典
        start_date: 回测起始日期
        end_date: 回测结束日期
        extra_params: 额外回测参数（如 valuation_repo），会合并到 params 中
        enable_attribution: 是否启用归因计算（仅全周期回测启用，窗口回测不启用以保持性能）

    Returns:
        包含 annual_return, sharpe_ratio, max_drawdown, num_trades, total_return 的字典，
        启用归因时追加 allocation_effect, switch_win_rate, rolling_ir 字段，
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
            enable_attribution=enable_attribution,
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
        ret = {
            'annual_return': result.get('annual_return', 0) or 0,
            'sharpe_ratio': result.get('sharpe_ratio', 0) or 0,
            'max_drawdown': result.get('max_drawdown', 0) or 0,
            'num_trades': result.get('num_trades', 0) or 0,
            'total_return': total_return,
            'excess_return': result.get('excess_return', 0) or 0,
            'turnover_annual_pct': result.get('turnover_annual_pct', 0) or 0,
            'annual_cost_pct': result.get('annual_cost_pct', 0) or 0,
        }
        if enable_attribution:
            attr = result.get('attribution')
            ret['allocation_effect'] = attr.allocation_effect if attr else None
            ret['switch_win_rate'] = attr.switch_win_rate if attr else None
            ret['rolling_ir'] = attr.rolling_ir if attr else None
        return ret
    except Exception:
        return None


# 模块级变量，供 worker 进程 fork 后使用（避免每次 pickle data_dict）
_WORKER_DATA_DICT = None
_WORKER_STRATEGY_MODULE = None
_WORKER_EXTRA_PARAMS = None
_WORKER_WINDOWS = None
_WORKER_START_DATE = None
_WORKER_SELECTION_END_DATE = None
_WORKER_TEST_START_DATE = None
_WORKER_TEST_END_DATE = None


def _worker_init(data_dict, strategy_module, extra_params, windows, start_date,
                 selection_end_date, test_start_date, test_end_date):
    """worker 进程初始化，设置模块级变量"""
    global _WORKER_DATA_DICT, _WORKER_STRATEGY_MODULE, _WORKER_EXTRA_PARAMS
    global _WORKER_WINDOWS, _WORKER_START_DATE, _WORKER_SELECTION_END_DATE
    global _WORKER_TEST_START_DATE, _WORKER_TEST_END_DATE
    _WORKER_DATA_DICT = data_dict
    _WORKER_STRATEGY_MODULE = strategy_module
    _WORKER_EXTRA_PARAMS = extra_params
    _WORKER_WINDOWS = windows
    _WORKER_START_DATE = start_date
    _WORKER_SELECTION_END_DATE = selection_end_date
    _WORKER_TEST_START_DATE = test_start_date
    _WORKER_TEST_END_DATE = test_end_date


def _worker_process_combo(combo_info):
    """worker 进程处理单个参数组合

    Args:
        combo_info: (combo_tuple, param_names)

    Returns:
        单个组合的结果字典，或 None（失败时）
    """
    combo, param_names = combo_info
    params = dict(zip(param_names, combo))
    window_results = []

    # 跑所有验证窗口
    for w in _WORKER_WINDOWS:
        metrics = _run_single_backtest(
            _WORKER_STRATEGY_MODULE, _WORKER_DATA_DICT, params,
            w['val_start'], w['val_end'],
            extra_params=_WORKER_EXTRA_PARAMS,
        )
        if metrics is not None:
            window_results.append(metrics)

    # 只跑选择区间回测；最终测试集在预设确定后单独运行。
    selection_metrics = _run_single_backtest(
        _WORKER_STRATEGY_MODULE, _WORKER_DATA_DICT, params,
        _WORKER_START_DATE, _WORKER_SELECTION_END_DATE,
        extra_params=_WORKER_EXTRA_PARAMS,
        enable_attribution=False,
    )

    if not window_results and selection_metrics is None:
        return None

    # 窗口指标
    if window_results:
        avg_sharpe = sum(r['sharpe_ratio'] for r in window_results) / len(window_results)
        avg_drawdown = sum(r['max_drawdown'] for r in window_results) / len(window_results)
        avg_trades = sum(r['num_trades'] for r in window_results) / len(window_results)
        sharpes = [r['sharpe_ratio'] for r in window_results]
        robustness = calculate_robustness_score(sharpes)
        worst_sharpe = min(sharpes) if sharpes else 0
        window_total_returns = [r['total_return'] for r in window_results]
        window_cagr = _cagr_from_returns(window_total_returns)
    else:
        avg_sharpe = 0
        avg_drawdown = 0
        avg_trades = 0
        robustness = 0
        worst_sharpe = 0
        window_cagr = 0

    # 选择区间指标
    if selection_metrics is not None:
        selection_annual = selection_metrics['annual_return']
        selection_sharpe = selection_metrics['sharpe_ratio']
        selection_drawdown = selection_metrics['max_drawdown']
        selection_trades = selection_metrics['num_trades']
        selection_alloc = selection_metrics.get('allocation_effect')
        selection_switch_win = selection_metrics.get('switch_win_rate')
        selection_rolling_ir = selection_metrics.get('rolling_ir')
    else:
        selection_annual = 0
        selection_sharpe = 0
        selection_drawdown = 0
        selection_trades = 0
        selection_alloc = None
        selection_switch_win = None
        selection_rolling_ir = None

    return {
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
            'validation_annual_return': (
                sum(r['annual_return'] for r in window_results) / len(window_results)
                if window_results else 0
            ),
            'validation_sharpe_ratio': avg_sharpe,
            'validation_max_drawdown': avg_drawdown,
            'validation_num_trades': avg_trades,
            'evaluation_stage': 'validation',
            'data_window': {
                'start': _WORKER_START_DATE,
                'end': _WORKER_SELECTION_END_DATE,
            },
            'participates_in_selection': True,
            'selection_annual_return': selection_annual,
            'selection_sharpe_ratio': selection_sharpe,
            'selection_max_drawdown': selection_drawdown,
            'selection_num_trades': selection_trades,
            'allocation_effect': selection_alloc,
            'switch_win_rate': selection_switch_win,
            'rolling_ir': selection_rolling_ir,
        },
    }


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
    max_allowed_drawdown: Optional[float] = None,
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
        strategy_module: 策略模块（需有 run_backtest 函数），默认 None 时使用 multi_factor
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
        from strategy import multi_factor as strategy_module

    start_time = time.time()

    # 1. 保留最后12个月作为最终留出测试集，不参与参数选择。
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    proposed_test_start = end_dt - pd.DateOffset(months=12)
    if proposed_test_start > start_dt:
        test_start_date = proposed_test_start.strftime('%Y-%m-%d')
        test_end_date = end_dt.strftime('%Y-%m-%d')
        selection_end_date = (proposed_test_start - pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        test_start_date = None
        test_end_date = None
        selection_end_date = end_dt.strftime('%Y-%m-%d')

    # 2. 分割验证窗口（6个月窗口，最终测试集之外）
    windows = split_windows(start_date, selection_end_date, val_months=6)
    if len(windows) < 3:
        # 数据不足3个窗口，使用全量数据做单次优化
        windows = [{
            'train_start': None,
            'train_end': start_date,
            'val_start': start_date,
            'val_end': selection_end_date,
        }]

    # 3. 生成参数组合
    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]
    all_combinations = list(itertools.product(*param_values))
    if len(all_combinations) > max_combinations:
        # 均匀采样：确保核心参数（lookback_momentum等）有足够多样性
        # 而非简单截取前N个（会导致核心参数固定不变）
        step = len(all_combinations) / max_combinations
        all_combinations = [
            all_combinations[int(i * step)]
            for i in range(max_combinations)
        ]

    total_steps = len(all_combinations)

    # 4. 多进程并行：对每个参数组合只使用验证区间
    combo_infos = [(combo, param_names) for combo in all_combinations]

    # 判断 CPU 核数，并行跑（充分利用全部物理核）
    cpu_count = os.cpu_count() or 1
    n_workers = min(cpu_count, len(all_combinations))
    use_parallel = n_workers > 1 and len(all_combinations) > 1

    all_results = []
    if use_parallel:
        # fork 模式下 worker 继承父进程内存，data_dict 零拷贝
        ctx = get_context('fork')
        # chunksize: 每个worker分一批combo，减少IPC开销
        chunksize = max(1, len(combo_infos) // (n_workers * 4))
        with ctx.Pool(
            processes=n_workers,
            initializer=_worker_init,
            initargs=(data_dict, strategy_module, extra_params, windows, start_date,
                      selection_end_date, test_start_date, test_end_date),
        ) as pool:
            if progress_callback:
                # 带进度回调的 imap_unordered
                for i, result in enumerate(pool.imap_unordered(_worker_process_combo, combo_infos, chunksize=chunksize), 1):
                    if result is not None:
                        all_results.append(result)
                    progress_callback(i, total_steps, f"完成 {i}/{total_steps} 个参数组合")
            else:
                for result in pool.imap_unordered(_worker_process_combo, combo_infos, chunksize=chunksize):
                    if result is not None:
                        all_results.append(result)
    else:
        # 串行回退（单核或单组合）
        _worker_init(data_dict, strategy_module, extra_params, windows, start_date,
                     selection_end_date, test_start_date, test_end_date)
        for i, combo_info in enumerate(combo_infos, 1):
            result = _worker_process_combo(combo_info)
            if result is not None:
                all_results.append(result)
            if progress_callback:
                progress_callback(i, total_steps, f"完成 {i}/{total_steps} 个参数组合")

    elapsed_time = time.time() - start_time

    if not all_results:
        return {
            'presets': [],
            'windows': windows,
            'total_combinations': len(all_combinations),
            'elapsed_time': elapsed_time,
        }

    # 5. 动态选出3-7个差异化预设（按参数组合去重）
    # 基准收益筛选使用验证区间，不能读取最终测试集。
    benchmark_filtered_results = all_results
    benchmark_applied = False
    if min_full_annual_return is not None:
        benchmark_filtered_results = [
            r for r in all_results
            if r['metrics'].get('validation_annual_return', 0) > min_full_annual_return
        ]
        benchmark_applied = True
        if len(benchmark_filtered_results) < 3:
            # 筛选后组合数不足3个，回退到不筛选
            benchmark_filtered_results = all_results
            benchmark_applied = False

    # 回撤筛选：最大回撤（负数，如-44.75表示44.75%）不超过基准回撤
    # max_allowed_drawdown是负数（基准最大回撤），策略回撤比它更小（更接近0或更大的负数更小）才算通过
    # 例子：max_allowed_drawdown=-44.75，策略回撤-39 → 通过（-39 > -44.75，回撤更小）
    #       max_allowed_drawdown=-44.75，策略回撤-47 → 不通过（-47 < -44.75，回撤更大）
    # 注意：validation_max_drawdown是正数（backtrader用正数表示回撤幅度），需转换为负数比较
    drawdown_filtered = benchmark_filtered_results
    if max_allowed_drawdown is not None:
        drawdown_filtered = [
            r for r in benchmark_filtered_results
            if -r['metrics'].get('validation_max_drawdown', 0) >= max_allowed_drawdown
        ]
        if len(drawdown_filtered) < 3:
            # 回退：不使用回撤筛选
            drawdown_filtered = benchmark_filtered_results
        else:
            benchmark_filtered_results = drawdown_filtered

    # 归因筛选已延迟到最终预设生成后执行（性能优化：节省33%时间）
    # 归因筛选改为对最终选出的预设单独跑归因
    attribution_filtered_results = benchmark_filtered_results

    # 去重：按回测指标（年化+夏普+回撤）去重，而非参数字符串
    # 因为不同参数可能产生相同回测结果（如drawdown_threshold=0不触发止损）
    used_param_keys = set()
    presets = []

    for style in PRESET_STYLES:
        if len(presets) >= 7:
            break

        metric = style['metric']
        sort_order = style['sort_order']

        # 按当前风格的指标排序
        sorted_results = sorted(
            attribution_filtered_results,
            key=lambda x: x['metrics'].get(metric, float('-inf')),
            reverse=(sort_order == 'desc'),
        )

        # 应用筛选条件
        filtered = sorted_results
        if style.get('min_sharpe') is not None:
            min_s = style['min_sharpe']
            filtered = [r for r in filtered
                       if r['metrics'].get('validation_sharpe_ratio', 0) >= min_s]
            if not filtered:
                filtered = sorted_results
        if style.get('min_return_benchmark_ratio') is not None and min_full_annual_return is not None:
            min_r = min_full_annual_return * style['min_return_benchmark_ratio']
            filtered = [r for r in filtered
                       if r['metrics'].get('validation_annual_return', 0) > min_r]
            if not filtered:
                filtered = sorted_results
        if style.get('min_return') is not None:
            min_r = style['min_return']
            filtered = [r for r in filtered
                       if r['metrics'].get('validation_annual_return', 0) > min_r]
            if not filtered:
                filtered = sorted_results

        # 选择参数未被使用过的最优组合
        for result in filtered:
            param_key = tuple(
                (name, repr(result['params'].get(name)))
                for name in param_names
            )
            if param_key in used_param_keys:
                continue
            used_param_keys.add(param_key)
            presets.append({
                'key': style['key'],
                'name': style['name'],
                'params': result['params'].copy(),
                'metrics': result['metrics'].copy(),
            })
            break

    # 最终测试集只在预设确定后运行，结果不参与选择。
    if presets and test_start_date and test_end_date:
        for preset in presets:
            oos_metrics = _run_single_backtest(
                strategy_module, data_dict, preset['params'],
                test_start_date, test_end_date,
                extra_params=extra_params,
                enable_attribution=False,
            )
            if oos_metrics is not None:
                preset['metrics'].update({
                    'oos_annual_return': oos_metrics['annual_return'],
                    'oos_sharpe_ratio': oos_metrics['sharpe_ratio'],
                    'oos_max_drawdown': oos_metrics['max_drawdown'],
                    'oos_num_trades': oos_metrics['num_trades'],
                    'oos_total_return': oos_metrics['total_return'],
                    'oos_excess_return': oos_metrics.get('excess_return', 0),
                    'oos_turnover_annual_pct': oos_metrics.get('turnover_annual_pct', 0),
                    'oos_evaluation_stage': 'test',
                    'oos_status': 'available',
                    'oos_data_window': {
                        'start': test_start_date,
                        'end': test_end_date,
                    },
                    'oos_participates_in_selection': False,
                })
            else:
                preset['metrics'].update({
                    'oos_evaluation_stage': 'test',
                    'oos_status': 'unavailable',
                    'oos_data_window': {
                        'start': test_start_date,
                        'end': test_end_date,
                    },
                    'oos_participates_in_selection': False,
                })
    elif presets:
        for preset in presets:
            preset['metrics'].update({
                'oos_evaluation_stage': 'not_applicable',
                'oos_status': 'not_applicable',
                'oos_data_window': None,
                'oos_participates_in_selection': False,
            })

    # 对最终选出的预设单独跑归因（只跑N次而非全部组合）
    if presets and extra_params is not None:
        for preset in presets:
            try:
                attr_metrics = _run_single_backtest(
                    strategy_module, data_dict, preset['params'],
                    start_date, selection_end_date,
                    extra_params=extra_params,
                    enable_attribution=True,
                )
                if attr_metrics is not None:
                    preset['metrics']['allocation_effect'] = attr_metrics.get('allocation_effect')
                    preset['metrics']['switch_win_rate'] = attr_metrics.get('switch_win_rate')
                    preset['metrics']['rolling_ir'] = attr_metrics.get('rolling_ir')
            except Exception:
                preset['metrics']['allocation_effect'] = None
                preset['metrics']['switch_win_rate'] = None
                preset['metrics']['rolling_ir'] = None

    return {
        'presets': presets,
        'windows': windows,
        'selection_window': {'start': start_date, 'end': selection_end_date},
        'test_window': (
            {'start': test_start_date, 'end': test_end_date}
            if test_start_date else None
        ),
        'total_combinations': len(all_combinations),
        'elapsed_time': elapsed_time,
        'benchmark_applied': benchmark_applied,
        'benchmark_threshold': min_full_annual_return,
        'max_allowed_drawdown': max_allowed_drawdown,
        'all_results': all_results,
        'all_results_count': len(all_results),
        'benchmark_filtered_count': len(benchmark_filtered_results),
        'attribution_filtered_count': len(presets),
    }
