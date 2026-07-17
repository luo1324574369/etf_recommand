"""Walk-Forward参数预设优化脚本

精简参数范围，平衡优化质量和运行时间。
参数组合数: 36, 验证窗口数: 12, 总回测次数: 468
"""
import sys
import os
import time
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from config.settings import ETF_UNIVERSE, DB_PATH
from strategy.walk_forward import generate_walk_forward_presets

# 精简参数范围：36个组合（3×3×2×2），平衡覆盖度和速度
OPTIMIZATION_PARAM_RANGES = {
    'lookback_short': [20, 40, 60],
    'lookback_long': [120, 180, 250],
    'top_n': [2, 3],
    'rebalance_freq': [20, 60],
}


def main():
    init_db(DB_PATH)
    db = get_db(DB_PATH)
    price_repo = PriceRepository(db)

    print("=" * 70)
    print("Walk-Forward 参数预设优化")
    print("=" * 70)

    selected_codes = [e['code'] for e in ETF_UNIVERSE]
    print(f"ETF池: {len(selected_codes)} 只")

    data_dict = {}
    loaded_codes = []
    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if prices and len(prices) > 60:
            df = pd.DataFrame(prices)
            data_dict[code] = df
            loaded_codes.append(code)

    print(f"成功加载行情数据: {len(loaded_codes)} 只ETF")
    if len(loaded_codes) < len(selected_codes):
        missing = set(selected_codes) - set(loaded_codes)
        print(f"⚠️ 未加载（数据不足）: {missing}")

    if len(data_dict) < 3:
        print("❌ 可用ETF数量不足3只，无法运行优化")
        return

    start_date = "2019-01-01"
    end_date = "2024-12-31"
    print(f"\n回测区间: {start_date} ~ {end_date}")
    print(f"参数范围: {OPTIMIZATION_PARAM_RANGES}")

    total_combinations = 1
    for k, v in OPTIMIZATION_PARAM_RANGES.items():
        total_combinations *= len(v)
    print(f"参数组合数: {total_combinations}")

    # 计算预计时间
    from strategy.walk_forward import split_windows
    windows = split_windows(start_date, end_date, val_months=6)
    total_backtests = total_combinations * (len(windows) + 1)
    print(f"验证窗口数: {len(windows)}")
    print(f"总回测次数: {total_backtests}")
    print(f"预计时间: {total_backtests * 1.5 / 60:.1f} 分钟")
    print("\n开始优化...")
    print("-" * 70)

    start_time = time.time()
    last_print = [start_time]

    def on_progress(current, total, msg):
        pct = current / total * 100 if total > 0 else 0
        now = time.time()
        # 每30秒或完成时打印
        if now - last_print[0] >= 30 or current == total:
            elapsed = now - start_time
            if current > 0:
                eta = (total - current) / current * elapsed
                print(f"[{current}/{total}] {pct:.1f}% - 已用{elapsed:.0f}s, 预计剩余{eta:.0f}s - {msg[:60]}")
            else:
                print(f"[{current}/{total}] {pct:.1f}% - {msg[:60]}")
            last_print[0] = now

    wf_result = generate_walk_forward_presets(
        data_dict,
        start_date,
        end_date,
        OPTIMIZATION_PARAM_RANGES,
        max_combinations=144,
        progress_callback=on_progress,
    )

    elapsed = wf_result.get('elapsed_time', 0)
    print("-" * 70)
    print(f"\n✅ 优化完成！耗时: {elapsed:.1f}s ({elapsed/60:.1f}分钟)")
    print(f"验证窗口数: {len(wf_result.get('windows', []))}")
    print(f"总参数组合数: {wf_result.get('total_combinations', 0)}")

    presets = wf_result.get('presets', [])
    if not presets:
        print("❌ 未能生成预设")
        return

    print(f"\n生成 {len(presets)} 个差异化参数预设：")
    print("=" * 110)

    for i, p in enumerate(presets, 1):
        m = p['metrics']
        params = p['params']
        print(f"\n【预设 {i}】{p['name']}")
        print(f"  参数: lookback_short={params.get('lookback_short')}, "
              f"lookback_long={params.get('lookback_long')}, "
              f"top_n={params.get('top_n')}, "
              f"rebalance_freq={params.get('rebalance_freq')}")
        print(f"  --- 全周期指标 ---")
        print(f"  年化收益: {m.get('full_annual_return', 0):.2f}%")
        print(f"  夏普比率: {m.get('full_sharpe_ratio', 0):.2f}")
        print(f"  最大回撤: {m.get('full_max_drawdown', 0):.2f}%")
        print(f"  交易次数: {m.get('full_num_trades', 0)}")
        print(f"  --- 窗口验证指标 ---")
        print(f"  窗口CAGR: {m.get('cagr', 0):.2f}%")
        print(f"  平均夏普: {m.get('avg_sharpe_ratio', 0):.2f}")
        print(f"  最差夏普: {m.get('worst_sharpe', 0):.2f}")
        print(f"  平均回撤: {m.get('avg_max_drawdown', 0):.2f}%")
        print(f"  鲁棒性得分: {m.get('robustness_score', 0):.2f}")
        print(f"  验证窗口数: {m.get('validation_windows', 0)}")

    print("\n" + "=" * 110)
    print("\n📊 预设对比汇总表:")
    print("-" * 110)
    header = f"{'预设风格':<22} {'年化%':>8} {'夏普':>6} {'回撤%':>8} {'CAGR%':>8} {'鲁棒性':>8} {'参数'}"
    print(header)
    print("-" * 110)
    for p in presets:
        m = p['metrics']
        params = p['params']
        param_str = f"ls={params.get('lookback_short')},ll={params.get('lookback_long')},n={params.get('top_n')},f={params.get('rebalance_freq')}"
        print(f"{p['name']:<22} "
              f"{m.get('full_annual_return', 0):>8.2f} "
              f"{m.get('full_sharpe_ratio', 0):>6.2f} "
              f"{m.get('full_max_drawdown', 0):>8.2f} "
              f"{m.get('cagr', 0):>8.2f} "
              f"{m.get('robustness_score', 0):>8.2f} "
              f"{param_str}")
    print("-" * 110)

    # 保存结果
    output_path = PROJECT_ROOT / "walk_forward_presets_result.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(wf_result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 详细结果已保存至: {output_path}")


if __name__ == "__main__":
    main()
