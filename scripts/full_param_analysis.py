"""全量参数分析（使用全部股票池）：运行所有参数组合，按多维度排名输出推荐"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import itertools
import time
import json
import pandas as pd
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.etf_repo import ETFRepository
from strategy import dual_momentum, valuation_dca
from config.settings import ETF_UNIVERSE

START_DATE = "2019-01-01"
END_DATE = "2024-12-31"
INITIAL_CAPITAL = 1000000

db_path = "data/etf.db"
init_db(db_path)
price_repo = PriceRepository(get_db(db_path))
etf_repo = ETFRepository(get_db(db_path))

# 从配置加载全部ETF代码，筛选有数据的
all_codes = [item["code"] for item in ETF_UNIVERSE]
data_dict = {}
missing_codes = []

for code in all_codes:
    prices = price_repo.get_daily_price(code)
    if prices:
        df = pd.DataFrame(prices)
        if len(df) >= 250:
            data_dict[code] = df
        else:
            missing_codes.append(f"{code}(数据不足{len(df)}条)")
    else:
        missing_codes.append(f"{code}(无数据)")

print(f"{'='*100}")
print(f"股票池统计")
print(f"{'='*100}")
print(f"配置池总数: {len(all_codes)} 只")
print(f"有效数据: {len(data_dict)} 只")
print(f"缺失/不足数据: {len(missing_codes)} 只")
if missing_codes:
    print(f"  缺失列表: {missing_codes}")
print(f"回测区间: {START_DATE} ~ {END_DATE}")
print(f"有效ETF列表:")
for code in sorted(data_dict.keys()):
    info = next((i for i in ETF_UNIVERSE if i["code"] == code), {})
    print(f"  {code} - {info.get('name', '')}")
print("=" * 100)


def run_full_optimization(strategy_module, param_ranges, strategy_name):
    """运行全量参数组合"""
    param_names = list(param_ranges.keys())
    param_values = [param_ranges[name] for name in param_names]
    all_combinations = list(itertools.product(*param_values))

    print(f"\n{'='*100}")
    print(f"🔍 {strategy_name} - 全量参数分析")
    print(f"{'-'*60}")
    print(f"参数范围: {param_ranges}")
    print(f"总组合数: {len(all_combinations)}")
    print(f"{'-'*60}")

    results = []
    start_time = time.time()
    success_count = 0
    fail_count = 0

    for idx, combo in enumerate(all_combinations):
        params = dict(zip(param_names, combo))
        try:
            result = strategy_module.run_backtest(
                data_dict,
                initial_capital=INITIAL_CAPITAL,
                start_date=START_DATE,
                end_date=END_DATE,
                **params,
            )
            result['params'] = params.copy()
            result['param_str'] = ', '.join(f"{k}={v}" for k, v in params.items())
            results.append(result)
            success_count += 1
        except Exception as e:
            fail_count += 1
            if fail_count <= 3:
                print(f"  [ERROR] params={params}: {e}")

    elapsed = time.time() - start_time
    print(f"\n完成: 成功{success_count} / 失败{fail_count}, 耗时{elapsed:.1f}s")

    return results


def rank_and_print(results, strategy_name):
    """按多维度排名输出"""
    if not results:
        print("无有效结果")
        return

    print(f"\n{'='*100}")
    print(f"📊 {strategy_name} - 多维度排名分析")
    print(f"{'='*100}")

    # --- 维度1: 夏普比率 ---
    by_sharpe = sorted(results, key=lambda x: x.get('sharpe_ratio', float('-inf')), reverse=True)
    print(f"\n🥇 排名维度1: 夏普比率（风险调整后收益）")
    print(f"{'排名':>4} | {'参数':<55} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'交易':>4}")
    print("-" * 110)
    for i, r in enumerate(by_sharpe[:10], 1):
        print(f"{i:4d} | {r['param_str']:<55} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['num_trades']:4d}")

    # --- 维度2: 年化收益率 ---
    by_annual = sorted(results, key=lambda x: x.get('annual_return', float('-inf')), reverse=True)
    print(f"\n🥈 排名维度2: 年化收益率")
    print(f"{'排名':>4} | {'参数':<55} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'交易':>4}")
    print("-" * 110)
    for i, r in enumerate(by_annual[:10], 1):
        print(f"{i:4d} | {r['param_str']:<55} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['num_trades']:4d}")

    # --- 维度3: 最大回撤（越小越好） ---
    by_dd = sorted(results, key=lambda x: x.get('max_drawdown', float('inf')))
    print(f"\n🥉 排名维度3: 最大回撤（风险控制）")
    print(f"{'排名':>4} | {'参数':<55} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'交易':>4}")
    print("-" * 110)
    for i, r in enumerate(by_dd[:10], 1):
        print(f"{i:4d} | {r['param_str']:<55} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['num_trades']:4d}")

    # --- 维度4: 超额收益 ---
    by_excess = sorted(results, key=lambda x: x.get('excess_return', float('-inf')), reverse=True)
    print(f"\n🏅 排名维度4: 超额收益（vs沪深300基准）")
    print(f"{'排名':>4} | {'参数':<55} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'交易':>4}")
    print("-" * 110)
    for i, r in enumerate(by_excess[:10], 1):
        print(f"{i:4d} | {r['param_str']:<55} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['num_trades']:4d}")

    # --- 维度5: 综合评分（夏普+年化+回撤逆序+超额 加权） ---
    for r in results:
        score = 0
        score += r.get('sharpe_ratio', 0) * 0.30
        score += r.get('annual_return', 0) * 0.25
        score -= r.get('max_drawdown', 0) * 0.20  # 回撤越小越好
        score += r.get('excess_return', 0) * 0.15
        score += r.get('win_rate', 0) * 0.10
        r['composite_score'] = score

    by_composite = sorted(results, key=lambda x: x.get('composite_score', float('-inf')), reverse=True)
    print(f"\n🏆 排名维度5: 综合评分（夏普30%+年化25%+回撤20%+超额15%+胜率10%）")
    print(f"{'排名':>4} | {'参数':<55} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'综合分':>7}")
    print("-" * 115)
    for i, r in enumerate(by_composite[:10], 1):
        print(f"{i:4d} | {r['param_str']:<55} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['composite_score']:7.2f}")

    # 统计摘要
    print(f"\n📈 统计摘要:")
    total_returns = [r['total_return'] for r in results]
    sharpes = [r['sharpe_ratio'] for r in results]
    drawdowns = [r['max_drawdown'] for r in results]
    print(f"  总收益:   最高{max(total_returns):.2f}%  最低{min(total_returns):.2f}%  平均{sum(total_returns)/len(total_returns):.2f}%")
    print(f"  夏普比率: 最高{max(sharpes):.2f}  最低{min(sharpes):.2f}  平均{sum(sharpes)/len(sharpes):.2f}")
    print(f"  最大回撤: 最小{min(drawdowns):.2f}%  最大{max(drawdowns):.2f}%  平均{sum(drawdowns)/len(drawdowns):.2f}%")

    # 基准收益
    if results:
        bench = results[0].get('benchmark_return', 0)
        print(f"  基准收益(沪深300): {bench:.2f}%")
        beat_bench = sum(1 for r in results if r['total_return'] > bench)
        print(f"  跑赢基准的组合数: {beat_bench}/{len(results)} ({beat_bench/len(results)*100:.1f}%)")

    return by_composite


# === 参数范围定义 ===
DM_PARAM_RANGES = {
    'lookback_short': [20, 40, 60, 80],
    'lookback_long': [60, 120, 180, 250],
    'top_n': [1, 2, 3],
    'rebalance_freq': [10, 20, 60],
}

VD_PARAM_RANGES = {
    'dca_freq': [10, 20, 30],
    'low_pctile': [20, 30, 40],
    'high_pctile': [60, 70, 80],
    'valuation_period': [120, 250],
}

# === 运行全量分析 ===
dm_results = run_full_optimization(dual_momentum, DM_PARAM_RANGES, "双动量轮动策略")
dm_ranked = rank_and_print(dm_results, "双动量轮动策略")

vd_results = run_full_optimization(valuation_dca, VD_PARAM_RANGES, "估值百分位定投策略")
vd_ranked = rank_and_print(vd_results, "估值百分位定投策略")

# === 跨策略综合推荐 ===
print(f"\n\n{'='*100}")
print(f"🏅🏅 跨策略综合推荐 Top 10")
print(f"{'='*100}")
all_results = []
for r in dm_results:
    r['strategy'] = '双动量轮动'
    all_results.append(r)
for r in vd_results:
    r['strategy'] = '估值定投'
    all_results.append(r)

all_sorted = sorted(all_results, key=lambda x: x.get('composite_score', float('-inf')), reverse=True)
print(f"{'排名':>4} | {'策略':<8} | {'参数':<50} | {'总收益%':>8} | {'年化%':>7} | {'夏普':>6} | {'回撤%':>7} | {'超额%':>8} | {'综合分':>7}")
print("-" * 125)
for i, r in enumerate(all_sorted[:10], 1):
    print(f"{i:4d} | {r['strategy']:<8} | {r['param_str']:<50} | {r['total_return']:8.2f} | {r['annual_return']:7.2f} | {r['sharpe_ratio']:6.2f} | {r['max_drawdown']:7.2f} | {r['excess_return']:8.2f} | {r['composite_score']:7.2f}")

print(f"\n✅ 全量参数分析完成！共测试 {len(dm_results)+len(vd_results)} 种组合")
