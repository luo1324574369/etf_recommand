# A股因子投资实操改进完整设计（P0+P1+P2）

> **日期**: 2026-07-26
> **背景**: 根据《A股因子投资实操指南》对项目进行符合度审计（65/100），针对9项关键差距进行全面改进
> **目标**: 提升策略的实盘可执行性、风控能力、因子有效性和市场适应性

---

## 一、改进内容概述

| # | 优先级 | 改进项 | 影响文件 |
|---|---|---|---|
| 1 | P0 | 换手率上限调整（100% → 30%） | `strategy/constraints.py` |
| 2 | P0 | 流动性前置过滤接入策略 | `strategy/multi_factor.py` |
| 3 | P0 | 组合回撤止损机制（回撤>15%→降仓50%） | `strategy/multi_factor.py` |
| 4 | P1 | 红利因子（dividend_yield纳入打分） | `strategy/scoring.py`, `strategy/multi_factor.py` |
| 5 | P1 | 滚动ICIR加权（新增icir_weighted_score函数） | `strategy/scoring.py`, `strategy/multi_factor.py` |
| 6 | P1 | 行业仓位上限（新增max_sector_exposure_pct=15%） | `strategy/constraints.py`, `strategy/multi_factor.py` |
| 7 | P2 | 滚动36个月IC检验 | `strategy/factor_analysis.py` |
| 8 | P2 | 市场状态识别 + 动态因子权重切换 | `strategy/multi_factor.py`, `strategy/scoring.py` |
| 9 | P2 | 因子失效监控（调仓前检查近6个月IC） | `strategy/multi_factor.py`, `strategy/factor_analysis.py` |

---

## 二、详细设计

### 改进1：换手率上限调整（P0）

**问题**：当前 `max_monthly_turnover=100.0`，允许每月整仓换一遍。按A股双边交易成本0.3%-0.5%计算，年化交易成本高达3.6%-6%，吃掉策略36%-60%的超额收益。

**方案**：
- 修改 `StrategyConstraints.__init__` 的 `max_monthly_turnover` 默认值从 `100.0` → `30.0`
- 修改 `DEFAULT_BACKTEST_CONSTRAINTS` 字典中 `max_monthly_turnover` 从 `100.0` → `30.0`
- 该约束已在 `can_buy`/`check_turnover` 流程中生效，无需额外改动

**影响范围**：所有使用 `DEFAULT_BACKTEST_CONSTRAINTS` 的回测入口统一生效

---

### 改进2：流动性前置过滤（P0）

**问题**：`LiquidityFilter` 类已存在但未被调用。日均成交额低于5000万的ETF滑点成本极高，回测收益虚高但实盘无法执行。

**方案**：在 `MultiFactorStrategy.__init__` 中为每个数据源添加20日日均成交额指标，在 `_compute_scores()` 入口处过滤。

**数据流**：
```
__init__:
  为每个d in self.datas添加:
    self.inds[d]['liquidity'] = bt.indicators.SumN(d.close * d.volume, period=20) / 20

_compute_scores:
  for d in self.datas:
    avg_amount = self.inds[d]['liquidity'][0]
    if avg_amount < 50_000_000:  # 5000万元
      continue  # 流动性不足，跳过
    # ... 原有打分逻辑
```

**关键设计决策**：
- 使用backtrader指标体系（与现有 `momentum`/`volatility` 指标风格一致）
- 阈值设为5000万元（与文章建议一致）
- 流动性检查在动量/波动率检查**之前**，避免对低流动性ETF做无意义计算

**新增策略参数**：
```python
('min_liquidity_amount', 50_000_000),  # 最低20日日均成交额（元），默认5000万
```

---

### 改进3：组合回撤止损（P0）

**问题**：当前策略无回撤止损机制，在熊市中可能持续大幅回撤。文章建议"组合回撤15%降仓5成"。

**方案**：使用backtrader的 `DrawDown` analyzer追踪最大回撤，当回撤>15%时自动降仓至50%。

**数据流**：
```
__init__:
  self._drawdown_analyzer = bt.analyzers.DrawDown()
  self._drawdown_reduced = False  # 是否已降仓标记

next (每个bar):
  max_dd = self._drawdown_analyzer.get_analysis().maxdrawdown
  if max_dd > 15 and not self._drawdown_reduced:
    self._reduce_positions_to_half()
    self._drawdown_reduced = True
  if max_dd < 5:
    self._drawdown_reduced = False
```

**降仓逻辑**：每个持仓减半（整数除法），不经过 `can_sell` 检查（风控优先）。

**新增策略参数**：
```python
('drawdown_threshold', 15.0),   # 回撤止损触发阈值（%），默认15%
('drawdown_recovery', 5.0),     # 回撤恢复阈值（%），默认5%
```

---

### 改进4：红利因子（P1）

**问题**：`etf_valuation` 表已存储 `dividend_yield` 字段，但未作为独立因子参与打分。文章指出红利因子是"全周期稳健类，年化超额收益3.4%~5.1%"。

**方案**：在 `scoring.py` 中新增红利因子支持，在 `multi_factor.py` 的 `_compute_scores()` 中获取并纳入因子计算。

**新增内容**：

1. **`scoring.py`**：在 `FACTOR_DIRECTIONS`、`DEFAULT_FACTORS`、`FACTOR_LABELS` 中添加：
   ```python
   "dividend_yield": 1,  # 红利因子：越高越好
   ```

2. **`scoring.py`**：在 `compute_all_factors` 中添加红利因子计算（从valuation数据获取）

3. **`multi_factor.py`**：在 `_get_pe_percentile` 基础上新增 `_get_dividend_yield` 方法：
   ```python
   def _get_dividend_yield(self, code: str) -> Optional[float]:
       if self.p.valuation_repo is None:
           return None
       try:
           latest_val = self.p.valuation_repo.get_latest_valuation(code)
           return float(latest_val.get('dividend_yield', 0)) if latest_val else None
       except Exception:
           return None
   ```

4. **`_compute_scores()`**：在因子字典中添加 `dividend_yield`（当所有ETF都有时）

**关键设计决策**：
- 红利因子方向为+1（越高越好）
- 仅当所有ETF都有红利数据时才纳入因子计算（与PE因子逻辑一致）
- 红利数据从 `etf_valuation` 表的 `dividend_yield` 字段获取（[valuation_repo.py:15](file:///Users/jianming.luo/Documents/person-project/etf_recommand/data/storage/valuation_repo.py#L15)）

---

### 改进5：滚动ICIR加权（P1）

**问题**：当前因子合成仅支持等权，文章建议进阶用"滚动ICIR加权"动态调整因子权重。

**方案**：在 `scoring.py` 中新增 `icir_weighted_score` 函数，基于过去N个月的ICIR动态计算因子权重。

**算法**：
```
ICIR权重 = ICIR / ΣICIR（所有因子）
综合得分 = Σ(zscore_i × ICIR权重_i)
```

**新增函数**（`strategy/scoring.py`）：
```python
def icir_weighted_score(
    zscores: Dict[str, Dict[str, float]],
    icir_values: Dict[str, float],
    factor_names: List[str] = None,
) -> Dict[str, float]:
    """基于滚动ICIR的因子加权合成

    Args:
        zscores: {code: {factor: zscore}}
        icir_values: {factor: icir} 各因子的滚动ICIR值
        factor_names: 参与合成的因子列表

    Returns:
        {code: weighted_score}
    """
    if not zscores:
        return {}

    if factor_names is None:
        factor_names = list(icir_values.keys())

    # 计算权重（ICIR越大权重越高）
    total_icir = sum(abs(icir_values.get(f, 0)) for f in factor_names)
    if total_icir == 0:
        return equal_weight_score(zscores, factor_names)

    weights = {
        f: abs(icir_values.get(f, 0)) / total_icir
        for f in factor_names
    }

    scores = {}
    for code, fs in zscores.items():
        weighted_sum = 0.0
        for f in factor_names:
            if f in fs:
                weighted_sum += fs[f] * weights[f]
        scores[code] = weighted_sum

    return scores
```

**数据流**：
```
_compute_scores:
  if self.p.weight_method == 'icir':
    # 获取滚动ICIR（从因子分析模块）
    icir_dict = self._get_rolling_icir()
    scores = icir_weighted_score(zscores, icir_dict, available_factors)
  elif self.p.weight_method == 'market_regime':
    # 风格轮动加权
    ...
  else:
    scores = equal_weight_score(zscores, available_factors)
```

**新增策略参数**：
```python
('weight_method', 'equal'),  # 加权方法: 'equal'=等权, 'icir'=滚动ICIR加权, 'market_regime'=风格轮动
```

---

### 改进6：行业仓位上限（P1）

**问题**：当前 `max_per_sector` 是计数限制（单赛道最多N只），按 `max_position_pct=40%` 计算，单赛道最多可达 2×40%=80%，远超文章建议的10%-15%。

**方案**：新增 `max_sector_exposure_pct` 参数，在 `can_buy` 中按行业聚合市值校验。

**新增约束参数**：
```python
# StrategyConstraints.__init__ 新增
max_sector_exposure_pct: float = 15.0,  # 单行业仓位上限(%)，默认15%

# DEFAULT_BACKTEST_CONSTRAINTS 新增
"max_sector_exposure_pct": 15.0,
```

**`can_buy` 新增检查逻辑**：
```python
# 行业仓位上限检查（按市值聚合）
if self.max_sector_exposure_pct > 0 and code_to_sector:
    target_sector = code_to_sector.get(code)
    if target_sector:
        sector_mv = sum(
            mv for c, mv in current_positions.items()
            if mv > 0 and code_to_sector.get(c) == target_sector
        )
        sector_mv += amount  # 本次买入金额
        sector_pct = sector_mv / total_value * 100
        if sector_pct > self.max_sector_exposure_pct:
            return False, f"{target_sector}行业持仓将达{sector_pct:.1f}%，超过上限{self.max_sector_exposure_pct}%"
```

---

### 改进7：滚动36个月IC检验（P2）

**问题**：当前 `factor_analysis.py` 仅产出静态IC序列，未提供滚动窗口（如36个月）的IC稳定性报告。文章建议"做滚动36个月的IC检验，确认因子不是单段行情偶然有效"。

**方案**：在 `factor_analysis.py` 中新增 `compute_rolling_ic` 函数，输出滚动IC时序与稳定性指标。

**新增函数**：
```python
def compute_rolling_ic(
    factor_df: pd.DataFrame,
    forward_df: pd.DataFrame,
    factor_name: str,
    window_months: int = 36,
) -> pd.DataFrame:
    """计算滚动窗口IC

    Args:
        factor_df: columns=['date', 'code', factor_name]
        forward_df: columns=['date', 'code', 'forward_return']
        factor_name: 因子名
        window_months: 滚动窗口（月），默认36个月

    Returns:
        DataFrame, columns=['date', 'rolling_ic_mean', 'rolling_ic_std', 'rolling_icir', 'rolling_ic_positive_ratio']
    """
    merged = pd.merge(factor_df, forward_df, on=['date', 'code'])
    merged = merged.sort_values('date')

    # 将日期转换为月份索引
    merged['month'] = merged['date'].dt.to_period('M')

    rows = []
    all_months = sorted(merged['month'].unique())

    for i in range(window_months, len(all_months) + 1):
        window_months_list = all_months[i - window_months:i]
        window_data = merged[merged['month'].isin(window_months_list)]

        if len(window_data) < 5:
            continue

        valid = window_data[[factor_name, 'forward_return']].dropna()
        if len(valid) < 5:
            continue

        corr, _ = spearmanr(valid[factor_name], valid['forward_return'])
        if np.isnan(corr):
            continue

        ic_series = []
        for date in sorted(window_data['date'].unique()):
            day_data = window_data[window_data['date'] == date]
            valid_day = day_data[[factor_name, 'forward_return']].dropna()
            if len(valid_day) >= 5:
                day_corr, _ = spearmanr(valid_day[factor_name], valid_day['forward_return'])
                if not np.isnan(day_corr):
                    ic_series.append(day_corr)

        if ic_series:
            rows.append({
                'date': window_months_list[-1].to_timestamp(),
                'rolling_ic_mean': np.mean(ic_series),
                'rolling_ic_std': np.std(ic_series, ddof=1),
                'rolling_icir': np.mean(ic_series) / np.std(ic_series, ddof=1) if np.std(ic_series, ddof=1) > 0 else 0,
                'rolling_ic_positive_ratio': sum(1 for ic in ic_series if ic > 0) / len(ic_series),
            })

    return pd.DataFrame(rows)
```

**输出指标**：
- rolling_ic_mean：滚动窗口IC均值
- rolling_ic_std：滚动窗口IC标准差
- rolling_icir：滚动窗口ICIR
- rolling_ic_positive_ratio：滚动窗口IC为正比例

---

### 改进8：市场状态识别 + 动态因子权重切换（P2）

**问题**：当前因子权重固定为等权，不随市场状态变化。文章建议"主线行情侧重动量/成长/高Beta，震荡/弱势侧重价值/红利/低波/反转"。

**方案**：基于沪深300指数20日均线判断市场状态，动态切换因子权重。

**市场状态判断**：
```python
def _detect_market_regime(self) -> str:
    """判断市场状态：基于沪深300（510300）20日均线

    Returns:
        'bull': 主线行情（大盘站上20日均线）
        'bear': 震荡/弱势行情
    """
    benchmark = self.getdatabyname('510300')
    if benchmark is None or len(benchmark) < 20:
        return 'bull'
    closes = [benchmark.close[-i] for i in range(20)]
    ma20 = sum(closes) / len(closes)
    return 'bull' if benchmark.close[0] >= ma20 else 'bear'
```

**权重切换规则**：

| 市场状态 | momentum_60d | pe_percentile | volatility_60d | dividend_yield | 归一化权重 |
|---|---|---|---|---|---|
| **主线行情** | 2.0 | 1.0 | 1.0 | 1.0 | (0.4, 0.2, 0.2, 0.2) |
| **震荡/弱势** | 1.0 | 2.0 | 2.0 | 2.0 | (0.17, 0.33, 0.33, 0.17) |

**数据流**：
```
_compute_scores:
  if self.p.weight_method == 'market_regime':
    regime = self._detect_market_regime()
    factor_weights = self._get_factor_weights_by_regime(regime, available_factors)
    scores = weighted_score(zscores, factor_weights, available_factors)
```

**新增策略参数**：
```python
('market_regime_switch', True),  # 是否开启风格轮动（True=双模式切换）
```

---

### 改进9：因子失效监控（P2）

**问题**：文章建议"单个因子连续6个月IC为负，暂时剔除出组合"。当前策略无因子失效监控机制。

**方案**：在调仓前检查最近6个月IC序列，若全为负则将该因子权重置0（暂不纳入打分）。

**监控逻辑**：
```python
def _check_factor_effectiveness(self, factor_names: list) -> dict:
    """检查因子有效性，返回因子权重（失效因子权重为0）

    Args:
        factor_names: 需要检查的因子名列表

    Returns:
        {factor: weight} 因子权重字典（失效因子weight=0）
    """
    if not hasattr(self, '_factor_ic_history'):
        # 首次调用，初始化IC历史
        self._factor_ic_history = {}

    weights = {}
    for factor in factor_names:
        ic_series = self._factor_ic_history.get(factor, [])

        # 检查最近6个月IC是否全为负
        if len(ic_series) >= 6:
            recent_ics = ic_series[-6:]
            if all(ic < 0 for ic in recent_ics):
                weights[factor] = 0.0  # 失效因子，权重为0
                continue

        weights[factor] = 1.0  # 有效因子，权重正常

    return weights
```

**数据流**：
```
_compute_scores:
  # 因子失效监控
  if self.p.monitor_factor_effectiveness:
      effectiveness_weights = self._check_factor_effectiveness(available_factors)
      # 将失效因子的zscore置0
      for code in zscores:
          for f in available_factors:
              if effectiveness_weights.get(f) == 0.0:
                  zscores[code][f] = 0.0
```

**新增策略参数**：
```python
('monitor_factor_effectiveness', False),  # 是否开启因子失效监控，默认关闭（需配合IC历史数据）
```

---

## 三、架构影响

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `strategy/constraints.py` | 修改 | 换手率默认值30；新增 `max_sector_exposure_pct` |
| `strategy/multi_factor.py` | 修改 | 流动性指标、回撤止损、红利因子、行业仓位检查、市场状态判断、因子失效监控 |
| `strategy/scoring.py` | 修改 | 新增红利因子配置、`weighted_score()`、`icir_weighted_score()` |
| `strategy/factor_analysis.py` | 修改 | 新增 `compute_rolling_ic()` |
| `strategy/optimizer.py` | 修改 | 参数网格新增 `weight_method`、`market_regime_switch` |

### 数据流变化

```
原流程:
  next() → _compute_scores() → zscore → equal_weight_score → sector_penalty → top_n

新流程:
  next()
    ├── 回撤止损检查（新增）
    └── _compute_scores()
        ├── 流动性过滤（新增）
        ├── 获取红利因子（新增）
        ├── zscore标准化
        ├── 因子失效监控（新增P2）
        ├── 加权合成（等权/ICIR/风格轮动，新增P1/P2）
        ├── sector_penalty
        └── top_n
```

---

## 四、测试设计

### 单元测试

**改进1 - 换手率**：
- `test_default_turnover_limit_is_30`
- `test_turnover_limit_blocks_excess`

**改进2 - 流动性过滤**：
- `test_liquidity_filter_low_amount`
- `test_liquidity_filter_sufficient`

**改进3 - 回撤止损**：
- `test_drawdown_trigger`
- `test_drawdown_no_trigger`
- `test_drawdown_recovery`

**改进4 - 红利因子**：
- `test_dividend_yield_factor`
- `test_dividend_yield_in_scoring`

**改进5 - 滚动ICIR加权**：
- `test_icir_weighted_score_basic`
- `test_icir_weighted_score_empty`

**改进6 - 行业仓位上限**：
- `test_max_sector_exposure_pct`
- `test_sector_exposure_limit_blocks_excess`

**改进7 - 滚动IC检验**：
- `test_compute_rolling_ic`
- `test_rolling_ic_window`

**改进8 - 市场状态识别**：
- `test_regime_detection_bull`
- `test_regime_detection_bear`

**改进9 - 因子失效监控**：
- `test_factor_effectiveness_monitor`
- `test_factor_effectiveness_inactive`

### 集成测试

- `test_full_backtest_with_all_improvements`：跑2022-2024完整回测，验证所有改进生效

---

## 五、风险与缓解

| # | 风险 | 缓解措施 |
|---|---|---|
| 1 | 换手率限制过严导致调仓不充分 | 起步用30%，如回测显示明显劣化可放宽至50% |
| 2 | 流动性过滤剔除过多ETF | 33只ETF池整体流动性较好，预计剔除0-2只 |
| 3 | 回撤止损在底部卖出造成损失 | 降仓50%而非清仓，保留反弹空间 |
| 4 | 红利因子数据缺失 | 仅当所有ETF都有红利数据时才纳入（与PE逻辑一致） |
| 5 | ICIR加权过度拟合 | 滚动ICIR使用过去12个月数据，避免过度优化 |
| 6 | 行业仓位限制过严 | 默认15%，可配置调整 |
| 7 | 因子失效监控误判 | 需要足够IC历史数据（至少6个月），默认关闭 |

---

## 六、参数网格更新

`strategy/optimizer.py` 的 `MULTI_FACTOR_PARAM_RANGES` 需要新增：

```python
MULTI_FACTOR_PARAM_RANGES = {
    'lookback_momentum': [20, 40, 60, 120],
    'lookback_volatility': [20, 60, 120],
    'top_n': [2, 3, 4, 5],
    'rebalance_freq': [10, 20, 60],
    'sector_penalty_factor': [0.5, 0.7, 1.0],
    'sector_exclude_threshold': [-0.10, -0.15, -0.20],
    'weight_method': ['equal', 'icir', 'market_regime'],  # 新增P1/P2
    'market_regime_switch': [True, False],  # 新增P2
}
```
