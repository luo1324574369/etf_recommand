# 交易指标数据源统一设计

**日期**: 2026-08-03
**状态**: 已批准
**作者**: AI + 用户共同设计

## 背景与问题

### 问题表现
回测概览显示的"交易次数"与交易明细表行数不一致。

### 根因分析

| 指标 | 数据源 | 计算口径 |
|---|---|---|
| 回测概览"交易次数" | `TradeAnalyzer.closed` | 已平仓交易对数（一开一平算1笔） |
| 交易明细行数 | `trade_log` (策略的 `_log_trade`) | 每次下单记1条（买/卖各1笔） |

两个数据源彼此独立，TradeAnalyzer 由 backtrader 内部维护，`trade_log` 由策略 `_log_trade()` 维护，两者没有同步关系。

### 衍生的其他一致性问题

1. **胜率/盈亏比口径不一致**：`win_rate`/`profit_factor` 来自 TradeAnalyzer 的"已平仓交易"，但交易明细展示的是逐笔PnL。
2. **换手率与交易记录不匹配**：`_turnover_records` 只统计调仓周期的买入金额，核心建仓等场景未完整记入。
3. **回撤止损卖出换手率虚高**：`record_turnover` 用 close价，`_log_trade` 用滑点价。

## 设计目标

1. 概览"交易次数" == 交易明细行数
2. 概览"胜率" == 明细中卖出笔 pnl>0 占比
3. 概览"换手率" == 明细中买入行金额累加 / 初始资金
4. 概览"盈亏比" == 明细中盈利卖出总和 / 亏损卖出总和
5. 全链路使用单一数据源，消除对账风险

## 设计决策

### 决策1：以 `trade_log` 为单一数据源

**采用方案**：方案A - 单一数据源

所有交易相关指标从 `trade_list` 派生，废弃 `TradeAnalyzer` 在指标层的依赖（cerebro中仍保留TradeAnalyzer，但不用于指标计算）。

**口径定义**：
- "交易次数" = 每次下单记1笔（买入算1笔，卖出算1笔）
- "胜率" = 卖出笔中 pnl>0 占比（买入笔 pnl=0 不参与）
- "盈亏比" = 总盈利卖出PnL / 总亏损卖出PnL（绝对值）
- "平均持仓天数" = 同code的FIFO配对买入到卖出间隔平均

### 决策2：换手率数据源统一

换手率也从 `trade_list` 派生，废弃 `_turnover_records`：

- `total_buys` = trade_list 中买入行的 amount 累加（已含滑点的实际买入金额）
- `turnover_total_pct` = total_buys / initial_capital * 100
- `turnover_annual_pct` = total_buys / initial_capital / years * 100
- `turnover_series` = trade_list 中买入行按 date 分组聚合 amount

### 决策3：核心建仓不计入换手率

- 核心仓位是静态配置，非轮动交易，不计入换手率
- `trade_log` 中新增 `trade_type` 字段标识交易类型：
  - `core`: 核心建仓
  - `satellite`: 卫星轮动
  - `stoploss`: 回撤止损
- 换手率计算时过滤 `trade_type != 'core'` 的买入行

### 决策4：交易明细加"交易类型"列

UI 的 `build_trade_table` 函数中新增"交易类型"列，让用户区分核心建仓、卫星轮动、回撤止损。

## 详细设计

### 模块1：backtest_utils.py 指标计算重构

**移除**：
- `trade_analyzer = strat.analyzers.trades.get_analysis()` 保留但不用于指标计算
- 旧的 num_trades/win_rate/profit_factor/avg_win/avg_lost/avg_hold 计算逻辑

**新增**：从 trade_list 派生指标的辅助函数

```python
def _compute_trade_metrics_from_log(trade_list, initial_capital, years):
    """从交易日志派生所有交易相关指标
    
    Args:
        trade_list: 策略的 trade_log
        initial_capital: 初始资金
        years: 回测年数
    
    Returns:
        dict: 包含 num_trades, win_rate, profit_factor, avg_win, avg_lost,
              avg_hold_days, turnover_total_pct, turnover_annual_pct, turnover_series
    """
    num_trades = len(trade_list)
    
    sell_records = [t for t in trade_list if t['direction'] == '卖出']
    win_sells = [t for t in sell_records if t['pnl'] > 0]
    loss_sells = [t for t in sell_records if t['pnl'] < 0]
    
    win_rate = len(win_sells) / len(sell_records) * 100 if sell_records else 0
    avg_win = sum(t['pnl'] for t in win_sells) / len(win_sells) if win_sells else 0
    avg_lost = abs(sum(t['pnl'] for t in loss_sells) / len(loss_sells)) if loss_sells else 0
    profit_factor = (
        sum(t['pnl'] for t in win_sells) / 
        abs(sum(t['pnl'] for t in loss_sells))
    ) if loss_sells else 0
    
    avg_hold_days = _compute_avg_hold_days_from_log(trade_list)
    
    # 换手率：仅统计非核心建仓的买入
    buy_records = [
        t for t in trade_list 
        if t['direction'] == '买入' and t.get('trade_type') != 'core'
    ]
    total_buys = sum(t['amount'] for t in buy_records)
    turnover_total_pct = total_buys / initial_capital * 100 if initial_capital > 0 else 0
    turnover_annual_pct = total_buys / initial_capital / years * 100 if years > 0 and initial_capital > 0 else 0
    
    # 换手率序列：按调仓日分组
    # total_value 无法从 trade_list 单独获得，需要从策略层获取
    # 设计：策略层在 _log_trade 时，如果是买入，附加当时的 total_value 到 trade_log
    # 简化方案：trade_list 的买入行已经包含 cash_after，但缺 total_value
    # 最终方案：trade_list 中买入行新增 total_value 字段（由 _log_trade 时 self.broker.getvalue() 获取）
    if buy_records:
        turnover_df = pd.DataFrame(buy_records)
        turnover_series = turnover_df.groupby('date').agg({
            'amount': 'sum',
            'total_value': 'first'  # 同一调仓日取首个total_value
        }).reset_index()
        turnover_series.columns = ['date', 'buy_amount', 'total_value']
        turnover_series['turnover_pct'] = (
            turnover_series['buy_amount'] / turnover_series['total_value'] * 100
        )
    else:
        turnover_series = pd.DataFrame()
    
    return {
        'num_trades': num_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_lost': avg_lost,
        'avg_hold_days': avg_hold_days,
        'turnover_total_pct': float(turnover_total_pct),
        'turnover_annual_pct': float(turnover_annual_pct),
        'turnover_series': turnover_series,
    }


def _compute_avg_hold_days_from_log(trade_list):
    """按FIFO配对计算平均持仓天数
    
    对每个code维护买入队列，遇到卖出时按FIFO消耗队列并累加持仓天数
    """
    from collections import defaultdict, deque
    from datetime import datetime
    
    buy_queues = defaultdict(deque)  # {code: deque([(date, shares), ...])}
    hold_days_list = []
    
    for t in trade_list:
        code = t.get('code')
        direction = t.get('direction')
        date_str = t.get('date')
        shares = t.get('quantity', 0)
        
        try:
            trade_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            continue
        
        if direction == '买入':
            buy_queues[code].append((trade_date, shares))
        elif direction == '卖出':
            remaining = shares
            while remaining > 0 and buy_queues[code]:
                buy_date, buy_shares = buy_queues[code][0]
                matched = min(remaining, buy_shares)
                hold_days = (trade_date - buy_date).days
                hold_days_list.append(hold_days)
                remaining -= matched
                buy_shares -= matched
                if buy_shares == 0:
                    buy_queues[code].popleft()
                else:
                    buy_queues[code][0] = (buy_date, buy_shares)
    
    return sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0
```

### 模块2：multi_factor.py `_log_trade` 签名扩展

```python
def _log_trade(self, d, direction, size, price, reason, trade_type='satellite'):
    """记录交易日志
    
    Args:
        trade_type: 'core' (核心建仓) | 'satellite' (卫星轮动) | 'stoploss' (回撤止损)
    """
    # ... 原有逻辑 ...
    # 新增 total_value 字段，供换手率序列使用
    total_value = self.broker.getvalue()
    self.trade_log.append({
        # ... 原有字段 ...
        'trade_type': trade_type,
        'total_value': total_value,
    })
```

**调用点修改**：
- 核心建仓 [multi_factor.py _build_core_position]: `_log_trade(..., trade_type='core')`
- 回撤止损 [_reduce_positions_to_half]: `_log_trade(..., trade_type='stoploss')`
- 卫星轮动调仓: 保持默认 `'satellite'`

### 模块3：移除 _turnover_records 相关代码

**移除**：
- `_turnover_records`、`_current_period_buys`、`_current_period_date` 状态变量
- `next()` 中换手率追踪逻辑（约15行）

### 模块4：UI层 - build_trade_table 加"交易类型"列

```python
def build_trade_table(trade_list):
    # ... 原有逻辑 ...
    trade_type_map = {
        'core': '🎯 核心',
        'satellite': '🛰️ 卫星',
        'stoploss': '🛑 止损',
    }
    rows.append({
        # ... 原有字段 ...
        '交易类型': trade_type_map.get(t.get('trade_type', 'satellite'), '🛰️ 卫星'),
    })
```

### 模块5：dual_momentum.py 同步

如 `dual_momentum.py` 有自己的 `_log_trade` 实现，同步签名变更。若无，无需改动。

## 影响面

| 模块 | 文件 | 改动类型 |
|---|---|---|
| 回测工具 | strategy/backtest_utils.py | 重构指标计算 |
| 策略层 | strategy/multi_factor.py | _log_trade 签名 + 移除 _turnover_records |
| 策略层 | strategy/dual_momentum.py | 同步 _log_trade 签名（如有） |
| Walk-Forward | strategy/walk_forward.py | 无需改（已读 result['num_trades']） |
| UI层 | presentation/streamlit_app.py | build_trade_table 加交易类型列 |
| 测试 | tests/test_multi_factor.py | 断言改为 num_trades == len(trade_list) |

## 回归测试验证清单

- [ ] 概览"交易次数" == 交易明细行数
- [ ] 概览"胜率" == 明细中卖出笔 pnl>0 占比
- [ ] 概览"换手率" == 明细中买入行金额累加 / 初始资金
- [ ] 概览"盈亏比" == 明细中盈利卖出总和 / 亏损卖出总和
- [ ] 核心建仓显示为"🎯 核心"，不计入换手率
- [ ] 回撤止损显示为"🛑 止损"
- [ ] Walk-Forward 优化流程正常
- [ ] 全套测试通过
