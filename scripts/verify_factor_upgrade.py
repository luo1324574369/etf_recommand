"""端到端验证：新因子方法论（MAD Winsorize + 分组zscore + 反转因子 + ICIR加权 + 失效剔除）

打印回测核心指标 + 因子诊断摘要，不改动任何文件。

用法:
  .venv/bin/python scripts/verify_factor_upgrade.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tabulate import tabulate
import pandas as pd

from config.settings import ETF_UNIVERSE, DB_PATH, PARAM_PRESETS
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.valuation_repo import ValuationRepo
from strategy import multi_factor

START = '2022-01-01'
END = '2024-12-31'


def load_data():
    init_db(DB_PATH)
    p = PriceRepository(get_db(DB_PATH))
    v = ValuationRepo(DB_PATH)
    data_dict = {}
    for e in ETF_UNIVERSE:
        prices = p.get_daily_price(e['code'])
        if prices and len(prices) > 252:
            df = pd.DataFrame(prices)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            data_dict[e['code']] = df
    return data_dict, v


def find_preset_params():
    presets = PARAM_PRESETS.get('多因子轮动', [])
    for ps in presets:
        if '均衡' in ps.get('name', ''):
            return ps.get('params') or {}
    return {}


def run(data_dict, v, params):
    r = multi_factor.run_backtest(
        data_dict,
        initial_capital=1000000,
        start_date=START, end_date=END,
        valuation_repo=v,
        **params,
    )
    return r


def main():
    data_dict, v = load_data()
    print(f"载入 {len(data_dict)} 只ETF, 区间 {START} ~ {END}\n")
    params = find_preset_params()
    print(f"参数预设: 均衡型 → {params}\n")

    r = run(data_dict, v, params)

    rows = [[
        f"{r.get('annual_return', float('nan')):.2%}",
        f"{r.get('sharpe_ratio', float('nan')):.3f}",
        f"{r.get('max_drawdown', float('nan')):.2%}",
        f"{r.get('win_rate', float('nan')):.1%}",
        f"{r.get('excess_return', float('nan')):+.2%}",
    ]]
    print(tabulate(rows, headers=['年化收益', '夏普', '最大回撤', '胜率', '超额'], tablefmt='github'))

    fd = r.get('factor_diagnostics')
    print("\n=== 因子诊断 ===")
    if not fd:
        print("factor_diagnostics 为空（策略可能未挂载 build_factor_diagnostics 或预热不足）")
        return
    print("weight_mode:", fd.get('weight_mode', 'n/a'))
    excluded = fd.get('excluded_factors') or []
    print("excluded_factors:", excluded or "无")

    fs = fd.get('factor_stats')
    if fs is None:
        fs = pd.DataFrame()
    if not fs.empty:
        show = fs[['factor', 'label', 'rank_ic_mean', 'icir', 'hit_rate_12m', 'status', 'used_weight_mean']].copy()
        show['rank_ic_mean'] = show['rank_ic_mean'].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "-")
        show['icir'] = show['icir'].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "-")
        show['hit_rate_12m'] = show['hit_rate_12m'].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "-")
        show['used_weight_mean'] = show['used_weight_mean'].apply(lambda x: f"{x:.2%}" if pd.notna(x) else "-")
        print("\n因子统计表:")
        print(tabulate(show.values.tolist(), headers=show.columns.tolist(), tablefmt='github'))
    else:
        print("factor_stats 为空")

    wh = fd.get('weight_history')
    if wh is None:
        wh = pd.DataFrame()
    print(f"\nweight_history rows: {len(wh)}")
    ric = fd.get('rolling_ic_series')
    if ric is None:
        ric = pd.DataFrame()
    print(f"rolling_ic_series rows: {len(ric)}")

    print("\nupgrade smoke check: OK")


if __name__ == '__main__':
    main()
