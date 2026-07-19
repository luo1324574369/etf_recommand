import itertools
import time
from typing import Dict, List, Any
import pandas as pd


def optimize_parameters(
    strategy_module,
    data_dict: Dict[str, pd.DataFrame],
    param_ranges: Dict[str, List[Any]],
    start_date=None,
    end_date=None,
    initial_capital=1000000,
    commission_rate=0.0003,
    target_metric: str = 'sharpe_ratio',
    max_combinations: int = 50,
) -> Dict[str, Any]:
    """
    参数优化：网格搜索寻找最优参数组合

    Args:
        strategy_module: 策略模块（如 dual_momentum, valuation_dca）
        data_dict: 行情数据
        param_ranges: 参数范围字典，如 {'top_n': [1,2,3], 'rebalance_freq': [20,60]}
        target_metric: 优化目标指标
        max_combinations: 最大组合数限制

    Returns:
        {'best_params': {}, 'best_result': {}, 'all_results': [], 'elapsed_time': float}
    """
    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]

    all_combinations = list(itertools.product(*param_values))
    if len(all_combinations) > max_combinations:
        all_combinations = all_combinations[:max_combinations]

    results = []
    start_time = time.time()

    for idx, combo in enumerate(all_combinations):
        params = dict(zip(param_names, combo))

        try:
            result = strategy_module.run_backtest(
                data_dict,
                initial_capital=initial_capital,
                commission_rate=commission_rate,
                start_date=start_date,
                end_date=end_date,
                **params,
            )

            result['params'] = params.copy()
            result['param_str'] = ', '.join(f"{k}={v}" for k, v in params.items())
            results.append(result)

        except Exception as e:
            continue

    elapsed_time = time.time() - start_time

    if not results:
        return {
            'best_params': {},
            'best_result': {},
            'all_results': [],
            'elapsed_time': elapsed_time,
        }

    if target_metric == 'excess_return':
        results.sort(key=lambda x: x.get('excess_return', float('-inf')), reverse=True)
    elif target_metric == 'annual_return':
        results.sort(key=lambda x: x.get('annual_return', float('-inf')), reverse=True)
    elif target_metric == 'sharpe_ratio':
        results.sort(key=lambda x: x.get('sharpe_ratio', float('-inf')), reverse=True)
    elif target_metric == 'max_drawdown':
        results.sort(key=lambda x: x.get('max_drawdown', float('inf')))
    else:
        results.sort(key=lambda x: x.get(target_metric, float('-inf')), reverse=True)

    best_result = results[0]

    return {
        'best_params': best_result.get('params', {}),
        'best_result': {k: v for k, v in best_result.items() if k != 'params' and k != 'param_str'},
        'all_results': results,
        'elapsed_time': elapsed_time,
        'total_combinations': len(all_combinations),
        'target_metric': target_metric,
    }


MULTI_FACTOR_PARAM_RANGES = {
    'lookback_momentum': [20, 40, 60, 120],
    'lookback_volatility': [20, 60, 120],
    'top_n': [2, 3, 4, 5],
    'rebalance_freq': [10, 20, 60],
}
# 4 × 3 × 4 × 3 = 144 组合，与双动量规模对齐
