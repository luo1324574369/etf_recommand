"""端到端数据一致性验证

跑一次短周期回测，验证：
- num_trades == len(trade_list)
- win_rate == 卖出笔 pnl>0 占比
- profit_factor == 盈利卖出总和 / 亏损卖出总和
- turnover_total_pct == 非核心买入金额累加 / 初始资金
- trade_list 中包含 trade_type 字段，值在 {core, satellite, stoploss} 中
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import datetime
from data.storage.db import init_db, get_db
from data.storage.price_repo import PriceRepository
from data.storage.etf_repo import ETFRepository
from data.storage.valuation_repo import ValuationRepo
from config.settings import ETF_UNIVERSE, DB_PATH, PARAM_PRESETS
from strategy import multi_factor
from strategy.constraints import StrategyConstraints

INITIAL_CAPITAL = 1000000
START = '2023-01-01'
END = '2024-12-31'

init_db(DB_PATH)
price_repo = PriceRepository(get_db(DB_PATH))
valuation_repo = ValuationRepo(DB_PATH)

# 选取数据充足的5只ETF做验证
candidates = ['510300', '510500', '159915', '512000', '510050']
selected = []
for code in candidates:
    prices = price_repo.get_daily_price(code)
    if prices and len(prices) >= 120:
        df = pd.DataFrame(prices)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        if df['trade_date'].min() <= pd.to_datetime(START) - pd.Timedelta(days=90):
            selected.append(code)
            print(f"加载 {code}: {len(df)} 条，起始 {df['trade_date'].min().date()}")
print(f"\n共加载 {len(selected)} 只ETF")

data_dict = {}
for code in selected:
    prices = price_repo.get_daily_price(code)
    data_dict[code] = pd.DataFrame(prices)

# 取第一个预设
presets = PARAM_PRESETS.get('多因子轮动', [])
preset_params = presets[0]['params'] if presets else {}
print(f"\n使用预设: {presets[0]['name'] if presets else 'N/A'}")

constraints_dict = {
    "long_only": True,
    "max_positions": 5,
    "min_positions": 1,
    "max_position_pct": 30,
    "max_total_exposure_pct": 95,
    "slippage_rate": 0.1,
    "t_plus_one": True,
    "min_trade_amount": 5000,
    "max_monthly_turnover": 100,
    "max_per_sector": 3,
    "core_allocation_pct": 50.0,
    "core_etf_codes": ("510300", "510500"),
    "core_weights": (0.5, 0.5),
    "max_sector_exposure_pct": 50.0,
}

params = dict(preset_params)
params['constraints'] = constraints_dict
params['valuation_repo'] = valuation_repo
params['enable_attribution'] = False

print(f"\n开始回测 {START} ~ {END} ...")
result = multi_factor.run_backtest(
    data_dict,
    initial_capital=INITIAL_CAPITAL,
    start_date=START,
    end_date=END,
    **params,
)

trade_list = result['trade_list']
print(f"\n========== 数据一致性验证 ==========")
print(f"回测区间: {START} ~ {END}")
print(f"初始资金: {INITIAL_CAPITAL:,.0f}")
print(f"最终市值: {result['final_value']:,.2f}")
print(f"总收益: {result['total_return']:.2f}%")
print(f"年化收益: {result['annual_return']:.2f}%")
print(f"夏普比率: {result['sharpe_ratio']:.2f}")
print(f"最大回撤: {result['max_drawdown']:.2f}%")

# 1. num_trades == len(trade_list)
assert result['num_trades'] == len(trade_list), \
    f"❌ num_trades({result['num_trades']}) != len(trade_list)({len(trade_list)})"
print(f"\n✅ 1. num_trades == len(trade_list) == {result['num_trades']}")

# 2. win_rate == 卖出笔 pnl>0 占比
sell_records = [t for t in trade_list if t.get('direction') == '卖出']
win_sells = [t for t in sell_records if t.get('pnl', 0) > 0]
loss_sells = [t for t in sell_records if t.get('pnl', 0) < 0]
expected_win_rate = (len(win_sells) / len(sell_records) * 100) if sell_records else 0
assert abs(result['win_rate'] - expected_win_rate) < 0.01, \
    f"❌ win_rate({result['win_rate']}) != expected({expected_win_rate})"
print(f"✅ 2. win_rate == {result['win_rate']:.2f}% (卖出{len(sell_records)}笔，盈利{len(win_sells)}笔)")

# 3. profit_factor == 盈利卖出总和 / 亏损卖出总和
total_win = sum(t['pnl'] for t in win_sells)
total_loss = abs(sum(t['pnl'] for t in loss_sells))
expected_pf = total_win / total_loss if total_loss > 0 else 0
assert abs(result['profit_factor'] - expected_pf) < 0.01, \
    f"❌ profit_factor({result['profit_factor']}) != expected({expected_pf})"
print(f"✅ 3. profit_factor == {result['profit_factor']:.2f} (盈利{total_win:.0f}/亏损{total_loss:.0f})")

# 4. turnover_total_pct == 非核心买入金额累加 / 初始资金
sat_buys = [t for t in trade_list
            if t.get('direction') == '买入' and t.get('trade_type') != 'core']
total_buys = sum(t.get('amount', 0) for t in sat_buys)
expected_turnover = total_buys / INITIAL_CAPITAL * 100
assert abs(result['turnover_total_pct'] - expected_turnover) < 0.01, \
    f"❌ turnover_total_pct({result['turnover_total_pct']}) != expected({expected_turnover})"
print(f"✅ 4. turnover_total_pct == {result['turnover_total_pct']:.2f}% "
      f"(卫星买入{len(sat_buys)}笔，金额{total_buys:,.0f})")

# 5. trade_type 字段检查
valid_types = {'core', 'satellite', 'stoploss'}
type_set = set(t.get('trade_type', 'satellite') for t in trade_list)
assert type_set.issubset(valid_types), f"❌ 出现非法 trade_type: {type_set - valid_types}"
type_counts = {}
for t in trade_list:
    tt = t.get('trade_type', 'satellite')
    type_counts[tt] = type_counts.get(tt, 0) + 1
print(f"✅ 5. trade_type 全部合法: {type_counts}")

# 6. 核心建仓明细
core_buys = [t for t in trade_list if t.get('trade_type') == 'core' and t.get('direction') == '买入']
print(f"\n核心建仓交易: {len(core_buys)} 笔")
for t in core_buys:
    print(f"  {t['date']} {t['code']} 数量{t['quantity']} 价格{t['price']:.3f} 金额{t['amount']:,.0f}")

# 7. 回撤止损（如有）
stoploss_sells = [t for t in trade_list if t.get('trade_type') == 'stoploss']
print(f"\n回撤止损交易: {len(stoploss_sells)} 笔")

# 8. avg_hold_days > 0（有配对时）
if sell_records:
    assert result['avg_hold_days'] > 0, f"❌ avg_hold_days={result['avg_hold_days']}"
    print(f"\n✅ 6. avg_hold_days == {result['avg_hold_days']:.1f} 天")

print("\n========== 所有一致性检查通过 ==========")
