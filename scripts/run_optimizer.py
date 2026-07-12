"""运行参数优化，输出最优策略参数"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.etf_repo import ETFRepository
from data.storage.valuation_repo import ValuationRepo
from strategy import dual_momentum, valuation_dca
from strategy.optimizer import optimize_parameters, DUAL_MOMENTUM_PARAM_RANGES, VALUATION_DCA_PARAM_RANGES

SELECTED_CODES = ["510300", "510500", "512480"]
START_DATE = "2019-01-01"
END_DATE = "2024-12-31"
INITIAL_CAPITAL = 1000000

db_path = "data/etf.db"
init_db(db_path)
price_repo = PriceRepository(get_db(db_path))
etf_repo = ETFRepository(get_db(db_path))
valuation_repo = ValuationRepo(db_path)

# 加载数据
data_dict = {}
for code in SELECTED_CODES:
    prices = price_repo.get_daily_price(code)
    if prices:
        data_dict[code] = pd.DataFrame(prices)

print(f"已加载 {len(data_dict)} 只ETF数据: {list(data_dict.keys())}")
print(f"回测区间: {START_DATE} ~ {END_DATE}")
print("=" * 80)

# === 双动量策略优化 ===
print("\n🔍 双动量轮动策略 - 参数优化")
print("-" * 60)
print(f"参数范围: {DUAL_MOMENTUM_PARAM_RANGES}")
opt_dm = optimize_parameters(
    dual_momentum,
    data_dict,
    DUAL_MOMENTUM_PARAM_RANGES,
    start_date=START_DATE,
    end_date=END_DATE,
    initial_capital=INITIAL_CAPITAL,
    target_metric='sharpe_ratio',
)

if opt_dm['all_results']:
    print(f"\n总组合数: {opt_dm['total_combinations']}, 耗时: {opt_dm['elapsed_time']:.1f}s")
    print(f"优化目标: {opt_dm['target_metric']}")
    print(f"\n🏆 最优参数: {opt_dm['best_params']}")
    best = opt_dm['best_result']
    print(f"   总收益: {best['total_return']:.2f}%  年化: {best['annual_return']:.2f}%  夏普: {best['sharpe_ratio']:.2f}  最大回撤: {best['max_drawdown']:.2f}%  超额收益: {best['excess_return']:+.2f}%")

    print("\n📊 Top 10 参数组合:")
    for i, r in enumerate(opt_dm['all_results'][:10], 1):
        print(f"  {i:2d}. {r.get('param_str','')} → 总收益{r['total_return']:.2f}% 年化{r['annual_return']:.2f}% 夏普{r['sharpe_ratio']:.2f} 回撤{r['max_drawdown']:.2f}% 超额{r['excess_return']:+.2f}%")

# === 估值定投策略优化 ===
print("\n\n🔍 估值百分位定投策略 - 参数优化")
print("-" * 60)
print(f"参数范围: {VALUATION_DCA_PARAM_RANGES}")
opt_vd = optimize_parameters(
    valuation_dca,
    data_dict,
    VALUATION_DCA_PARAM_RANGES,
    start_date=START_DATE,
    end_date=END_DATE,
    initial_capital=INITIAL_CAPITAL,
    target_metric='sharpe_ratio',
)

if opt_vd['all_results']:
    print(f"\n总组合数: {opt_vd['total_combinations']}, 耗时: {opt_vd['elapsed_time']:.1f}s")
    print(f"优化目标: {opt_vd['target_metric']}")
    print(f"\n🏆 最优参数: {opt_vd['best_params']}")
    best = opt_vd['best_result']
    print(f"   总收益: {best['total_return']:.2f}%  年化: {best['annual_return']:.2f}%  夏普: {best['sharpe_ratio']:.2f}  最大回撤: {best['max_drawdown']:.2f}%  超额收益: {best['excess_return']:+.2f}%")

    print("\n📊 Top 10 参数组合:")
    for i, r in enumerate(opt_vd['all_results'][:10], 1):
        print(f"  {i:2d}. {r.get('param_str','')} → 总收益{r['total_return']:.2f}% 年化{r['annual_return']:.2f}% 夏普{r['sharpe_ratio']:.2f} 回撤{r['max_drawdown']:.2f}% 超额{r['excess_return']:+.2f}%")

print("\n" + "=" * 80)
print("✅ 参数优化完成")
