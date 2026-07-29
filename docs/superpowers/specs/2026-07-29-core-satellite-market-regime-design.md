# 核心卫星架构 + 多指标市场状态识别 设计文档

## 1. 背景与目标

### 1.1 问题
当前多因子轮动策略在2025年6-9月单边牛市中大幅跑输沪深300（策略+4.43% vs 沪深300+20.45%，超额-16.02%），核心原因：
1. 缺少Beta暴露：分散持仓在单边牛市中必然跑输指数
2. 市场状态识别过于敏感：MA20单指标+无滞后确认，6个月内16次状态切换，因子权重反复调整
3. 20日动量太短：短期动量噪音大，追涨杀跌

### 1.2 目标
- 引入核心卫星架构，保证50%资金紧跟大盘Beta获取基础收益
- 改用多指标投票制+连续3日确认，减少假信号
- 最终效果：2025年6-11月单边牛市中，策略收益应显著高于现有水平（目标接近或超过沪深300的+20%）

---

## 2. 核心卫星仓位拆分架构

### 2.1 总体结构
```
总资金 100%
├── 核心仓位 50%（静态，永不调仓）
│   ├── 510300 沪深300ETF   25%（占总资金比例）
│   └── 510500 中证500ETF   25%（占总资金比例）
│
└── 卫星仓位 50%（多因子轮动，定期调仓）
    ├── ETF打分池：ETF_UNIVERSE全部33只（允许宽基重叠加配）
    ├── 因子：动量 + PE百分位 + 波动率 + 红利
    ├── 约束：赛道惩罚、换手率、行业上限、回撤止损
    └── 市场状态：因子权重动态调整
```

### 2.2 核心仓位规则
1. **建仓时机**：回测首日（`day_count == rebalance_freq - 1`），即卫星第一次调仓日
2. **建仓方式**：一次性按等权分配（510300占总资金25%，510500占总资金25%）
3. **持有规则**：建仓后永不卖出，不参与任何调仓逻辑
4. **约束豁免**：核心仓位不计入卫星的单只ETF仓位上限、行业仓位上限、换手率计算
5. **重复允许**：卫星仓位仍可持有510300或510500（即超配核心宽基），但卫星部分独立计算仓位

### 2.3 卫星仓位规则
1. **运作资金**：总资金 × 50%（卫星配额）
2. **单只持仓上限**：`max_position_pct` × 卫星配额 = 相对于总资金的上限
   - 例：`max_position_pct=40%`，单只卫星ETF上限为总资金的 40% × 50% = 20%
3. **行业仓位上限**：同样按卫星配额计算
4. **换手率计算**：只统计卫星仓位的买卖，核心仓位不计入
5. **回撤止损**：组合整体回撤（含核心+卫星）超过阈值时，卫星仓位降仓50%（核心仓位不动）

### 2.4 参数
| 参数 | 默认值 | 说明 |
|:---|:---|:---|
| core_allocation_pct | 50.0 | 核心仓位占总资金比例(%) |
| core_etf_codes | ["510300", "510500"] | 核心仓位ETF代码列表 |
| core_weights | [0.5, 0.5] | 核心仓位内部分配比例（等权）|

---

## 3. 市场状态识别 — 多指标投票制 + 滞后确认

### 3.1 判断基准
以 510300（沪深300ETF）的行情数据为判断依据。

### 3.2 三个指标（2/3 通过）

| 指标 | 看多信号 | 看空信号 |
|:---|:---|:---|
| **MA60 均线** | close > MA(close, 60) | close < MA(close, 60) |
| **MACD 金叉/死叉** | DIF 上穿 DEA（金叉出现日或DIF>DEA且上穿后的N日内）| DIF 下穿 DEA（死叉）|
| **成交额放大/萎缩** | volume > MA(volume, 20) × 1.2 | volume < MA(volume, 20) × 0.8 |

#### MACD 参数
- 快速EMA：12
- 慢速EMA：26
- DEA（信号线）：9
- 金叉判定：DIF[t-1] <= DEA[t-1] 且 DIF[t] > DEA[t]（或DIF上穿后5日内维持看多）
- 死叉判定：DIF[t-1] >= DEA[t-1] 且 DIF[t] < DEA[t]（或下穿后5日内维持看空）
- 注：MACD金叉/死叉是事件信号，事后保持5日有效。若当前无信号，则此项为"中性"（不计入看多也不计入看空，减少指标数量→改为MA60和成交额的1/2通过）

### 3.3 状态判定规则

每次调仓日（或next()每日判定，但切换需要连续确认）：

1. **计算3个指标投票**：
   - bull_votes：看多的指标数（0-3）
   - bear_votes：看空的指标数（0-3）

2. **基础判定**：
   - 若 bull_votes >= 2 → 候选 bull
   - 若 bear_votes >= 2 → 候选 bear
   - 否则 → 维持上期状态（中性不改变）

3. **滞后确认（连续3日）**：
   - 维护 `_candidate_regime`（候选状态）和 `_candidate_streak`（连续天数计数）
   - 当候选状态连续 3 日与当前状态不同 → 切换
   - 例：当前是 bull，出现连续3日候选bear → 切到bear
   - 避免单日反转的假信号

### 3.4 参数
| 参数 | 默认值 | 说明 |
|:---|:---|:---|
| regime_regime_method | "multi_vote" | 市场状态识别方法 |
| regime_regime_lookback | 60 | MA均线回看期（日）|
| regime_macd_fast | 12 | MACD快速EMA |
| regime_macd_slow | 26 | MACD慢速EMA |
| regime_macd_signal | 9 | MACD信号线 |
| regime_macd_signal_window | 5 | 金叉/死叉后信号保持天数 |
| regime_volume_threshold_up | 1.2 | 成交额看多阈值（倍）|
| regime_volume_threshold_down | 0.8 | 成交额看空阈值（倍）|
| regime_confirm_days | 3 | 滞后确认天数 |

---

## 4. 因子权重动态调整规则（沿用现有逻辑）

基于状态切换：
- **bull**：动量权重 ×1.3，其他因子 ×0.85，归一化
- **bear**：动量权重 ×0.7，PE百分位/波动率/红利 ×1.2，归一化
- **neutral**：等权

---

## 5. 代码改动点

### 5.1 strategy/multi_factor.py
- 新增参数：`core_allocation_pct`, `core_etf_codes`, `core_weights`
- 新增 `_core_positions` dict：记录核心仓位的code, shares, avg_price
- 新增 `_build_core_position()`：回测首日（和第一次调仓日同步）执行核心建仓
- 新增 `_core_total_value()`：核心仓位当前市值
- 新增 `_satellite_total_value()`：总市值 - 核心市值
- 修改 `_rebalance()`：
  - 判断是否为第一次调仓日 → 先建核心仓位
  - 调仓的买入/卖出只操作卫星仓位ETF（或核心持仓不纳入卫星卖出判断）
  - 所有仓位上限判断以 `_satellite_total_value()` 为分母
- 修改 `check_position_limits`、`check_turnover`：以卫星市值为基准
- 重写 `_get_market_regime()`：多指标投票制 + 3日确认
  - 新增3个辅助函数：`_check_ma_signal()`, `_check_macd_signal()`, `_check_volume_signal()`
  - 新增状态变量 `_candidate_regime`, `_candidate_streak`
- 修改 `next()`：每日更新市场状态候选计数（而不是每日直接切换）

### 5.2 strategy/constraints.py
- `BacktestConstraints` 新增 `core_allocation_pct`, `core_etf_codes`, `core_weights` 字段
- 将参数从策略参数映射到约束

### 5.3 strategy/optimizer.py
- MULTI_FACTOR_PARAM_RANGES 新增：
  - `core_allocation_pct`: [50.0]（固定，暂时不优化）
  - `regime_confirm_days`: [3]（固定）
  - `regime_method`: ["multi_vote"]（固定）
- 之后若需要可放开 core_allocation_pct 到 [40, 50, 60] 优化

### 5.4 config/settings.py
- PARAM_PRESETS 中的每个预设新增上述参数
- 不需要修改，因为优化器会自动写入

### 5.5 tests/test_multi_factor.py
- 新增 TestCoreSatellite 类：
  - test_core_position_built_on_first_day：核心仓位首日正确建仓
  - test_core_not_sold_in_rebalance：调仓时核心仓位不被卖出
  - test_satellite_position_limits_based_on_satellite：卫星仓位上限基于卫星市值计算
- 新增 TestMarketRegimeMultiVote 类：
  - test_three_indicators_vote_bull：3指标2/3看多 → bull候选
  - test_three_indicators_vote_bear：3指标2/3看空 → bear候选
  - test_three_day_confirmation_switch：连续3日候选才切换

---

## 6. 错误处理

1. 核心ETF的行情数据缺失 → 严格模式报错（和现有约束一致）
2. 核心ETF PE数据缺失 → 不影响，核心仓位不参与因子打分
3. MACD/MA计算数据不足（前60+26天）→ 默认返回 neutral，等数据充足后判断
4. 成交额数据缺失 → 该项指标视为中性，改为 MA60 + MACD 的 1/2 通过

---

## 7. 回测验证

### 7.1 验证时间区间
重点验证：2025-01-01 ~ 2025-12-01（单边牛市场景）
同时跑：2019-01-01 ~ 2024-12-31（全周期）

### 7.2 成功指标
- 2025年6-11月：策略收益应显著高于现有+4.43%，目标 > +12%（沪深300+20%的60%以上）
- 全周期最大回撤：仍 < 30%（优于沪深300的-44.75%）
- 市场状态切换次数：< 5 次/年（优于原16次/6个月）

---

## 8. 边界情况

1. **首日即下跌**：核心仓位50%建仓后立即下跌，但这是Beta暴露的代价，属于预期范围
2. **卫星选中核心ETF重叠**：允许，卫星中超配宽基是合理行为（看好宽基的动量/估值）
3. **核心仓位占比因涨跌偏离50%**：允许偏离（核心仓位涨得多→比例>50%；反之<50%），不做动态再平衡（保持"永不调仓"的原则，简单且减少交易）
4. **回撤止损时**：只对卫星仓位降仓，核心仓位持有不动；恢复阈值达到后，卫星仓位恢复
