# A股因子投资实操改进设计

> **日期**: 2026-07-26
> **背景**: 根据《A股因子投资实操指南》对项目进行符合度审计（65/100），针对4项关键差距进行改进
> **目标**: 提升策略的实盘可执行性、风控能力和市场适应性

---

## 一、改进内容概述

| # | 改进项 | 优先级 | 影响文件 |
|---|---|---|---|
| 1 | 换手率上限调整（100% → 30%） | P0 | `strategy/constraints.py` |
| 2 | 流动性前置过滤接入策略 | P0 | `strategy/multi_factor.py` |
| 3 | 组合回撤止损机制 | P0 | `strategy/multi_factor.py` |
| 4 | A股风格轮动（双模式切换） | P1 | `strategy/multi_factor.py`, `strategy/scoring.py` |

---

## 二、详细设计

### 改进1：换手率上限调整

**问题**：当前 `max_monthly_turnover=100.0`（[constraints.py:34](file:///Users/jianming.luo/Documents/person-project/etf_recommand/strategy/constraints.py#L34)），允许每月整仓换一遍。按A股双边交易成本0.3%-0.5%计算，年化交易成本高达3.6%-6%，会吃掉策略36%-60%的超额收益。

**方案**：
- 修改 `StrategyConstraints.__init__` 的 `max_monthly_turnover` 默认值从 `100.0` → `30.0`
- 修改 `DEFAULT_BACKTEST_CONSTRAINTS` 字典中 `max_monthly_turnover` 从 `100.0` → `30.0`
- 该约束已在 `can_buy`/`check_turnover` 流程中生效，无需额外改动

**影响范围**：
- 所有使用 `DEFAULT_BACKTEST_CONSTRAINTS` 的回测入口（Streamlit / Brinson归因 / Walk-Forward / 审计脚本）统一生效
- 已有的 `check_turnover()` 方法（[constraints.py:168-197](file:///Users/jianming.luo/Documents/person-project/etf_recommand/strategy/constraints.py#L168-L197)）会自动拦截超限交易

**验证标准**：
- 回测中月度换手率>30%时，`check_turnover` 返回 `(False, "月度换手率XX%超过上限30%")`
- 交易日志中应出现因换手率超限被拦截的记录

---

### 改进2：流动性前置过滤

**问题**：`LiquidityFilter` 类已存在于 [liquidity_filter.py](file:///Users/jianming.luo/Documents/person-project/etf_recommand/strategy/filters/liquidity_filter.py)，但未被 `multi_factor.py` 调用。日均成交额低于5000万的ETF滑点成本极高，回测收益虚高但实盘无法执行。

**方案**：在 `MultiFactorStrategy.__init__` 中为每个数据源添加20日日均成交额指标，在 `_compute_scores()` 入口处过滤。

**数据流**：

```
__init__:
  为每个d in self.datas添加:
    self.inds[d]['liquidity'] = bt.indicators.SumN(
        d.close * d.volume, period=20
    ) / 20  # 20日日均成交额（元）

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
- 该过滤**仅在调仓日生效**（`_compute_scores` 仅在调仓日调用），不影响每日指标更新

**边界情况**：
- 上市不足20天的新ETF：backtrader的 `SumN` 在数据不足时返回NaN，`_compute_scores` 中 `avg_amount is None or avg_amount < threshold` 时跳过该ETF
- 全部ETF都不满足流动性：返回空列表，策略自然清仓（已有逻辑处理）

---

### 改进3：组合回撤止损

**问题**：当前策略无回撤止损机制，在熊市中可能持续大幅回撤。文章建议"组合回撤15%降仓5成"。

**方案**：在 `MultiFactorStrategy` 中使用backtrader的 `DrawDown` analyzer追踪最大回撤，当回撤>15%时自动降仓至50%。

**数据流**：

```
__init__:
  self._add_analyzer(bt.analyzers.DrawDown, _name='drawdown')
  self._drawdown_reduced = False  # 是否已降仓标记

next (每个bar):
  drawdown = self.analyzers.drawdown.get_analysis()
  max_dd = drawdown.maxdrawdown  # 最大回撤百分比

  if max_dd > 15 and not self._drawdown_reduced:
    # 触发降仓：将持仓减至50%
    self._reduce_positions_to_half()
    self._drawdown_reduced = True

  # 当回撤恢复（如净值创新高）时重置标记
  if max_dd < 5:
    self._drawdown_reduced = False
```

**降仓逻辑**：

```python
def _reduce_positions_to_half(self):
    """将所有持仓减半"""
    for d in self.datas:
        pos = self.getposition(d)
        if pos.size > 0:
            sell_size = pos.size // 2  # 整数除以2
            if sell_size > 0:
                price = d.close[0]
                sell_price = self.constraints.apply_slippage_sell(price)
                self._log_trade(d, '卖出', sell_size, sell_price,
                               f"组合回撤止损，降仓50%")
                self.sell(d, size=sell_size, price=sell_price)
```

**关键设计决策**：
- 使用backtrader内置 `DrawDown` analyzer（准确、零额外状态维护）
- 触发阈值15%（与文章一致）
- 恢复阈值5%（避免频繁切换）
- 降仓方式：每个持仓减半（简单且可逆）
- 降仓操作**不经过 `can_sell` 检查**（风控优先于约束）
- 降仓后的现金**不再立即买入**（等待下一调仓日）

**边界情况**：
- 奇数手持仓：`pos.size // 2` 整数除法，剩余1手忽略
- 降仓后市场继续下跌：`_drawdown_reduced=True` 阻止重复降仓
- 降仓后市场恢复：当 `max_dd < 5%` 时重置标记，策略恢复正常运作
- 调仓日与降仓日重合：降仓优先执行，调仓逻辑中 `_compute_scores` 返回的selected_codes仍按正常流程买入

---

### 改进4：A股风格轮动（双模式切换）

**问题**：当前因子权重固定为等权，不随市场状态变化。A股风格轮动极强，静态多因子容易阶段性失效。

**方案**：基于沪深300指数20日均线判断市场状态，动态切换因子权重。

**市场状态判断**：

```python
def _detect_market_regime(self):
    """判断市场状态：'bull' 或 'bear'

    Returns:
        'bull': 主线行情（大盘站上20日均线）
        'bear': 震荡/弱势行情
    """
    # 获取沪深300（510300）数据
    benchmark = self.getdatabyname('510300')
    if benchmark is None:
        return 'bull'  # 默认主线行情

    closes = [benchmark.close[-i] for i in range(20)]
    ma20 = sum(closes) / len(closes)
    current = benchmark.close[0]

    return 'bull' if current >= ma20 else 'bear'
```

**权重切换规则**：

| 市场状态 | 动量因子 | 价值因子 | 低波因子 | 红利因子* | 归一化权重 |
|---|---|---|---|---|---|
| **主线行情** | 2.0 | 1.0 | 1.0 | 1.0 | (0.4, 0.2, 0.2, 0.2) |
| **震荡/弱势** | 1.0 | 2.0 | 2.0 | 2.0 | (0.17, 0.33, 0.33, 0.17) |

*红利因子暂未实现，本改进先落地前3个因子，红利因子作为后续P1任务

**实际权重配置**（3因子版本）：

| 市场状态 | momentum_60d | pe_percentile | volatility_60d | 归一化权重 |
|---|---|---|---|---|
| **主线行情** | 2.0 | 1.0 | 1.0 | (0.5, 0.25, 0.25) |
| **震荡/弱势** | 1.0 | 2.0 | 2.0 | (0.2, 0.4, 0.4) |

**数据流**：

```
_compute_scores:
  regime = self._detect_market_regime()

  if regime == 'bull':
    factor_weights = {'momentum_60d': 2.0, 'pe_percentile': 1.0, 'volatility_60d': 1.0}
  else:
    factor_weights = {'momentum_60d': 1.0, 'pe_percentile': 2.0, 'volatility_60d': 2.0}

  # 替换原有的 equal_weight_score 调用
  scores = weighted_score(zscores, factor_weights, factor_names=available_factors)
```

**关键设计决策**：
- 市场状态判断基于沪深300（510300）20日均线（与 [market_timing_filter.py](file:///Users/jianming.luo/Documents/person-project/etf_recommand/strategy/filters/market_timing_filter.py) 逻辑一致）
- 权重切换在 `zscore` 标准化之后、得分合成之前（不破坏标准化过程）
- 新增 `weighted_score()` 函数替代 `equal_weight_score()`，但保留 `equal_weight_score()` 作为默认选项
- 新增策略参数 `market_regime_switch`（默认True，可关闭）

**新增函数**（`strategy/scoring.py`）：

```python
def weighted_score(
    zscores: Dict[str, Dict[str, float]],
    factor_weights: Dict[str, float],
    factor_names: List[str] = None,
) -> Dict[str, float]:
    """加权合成因子得分

    Args:
        zscores: {code: {factor: zscore}}
        factor_weights: {factor: weight}
        factor_names: 参与合成的因子列表

    Returns:
        {code: weighted_score}
    """
    if not zscores:
        return {}

    if factor_names is None:
        factor_names = list(factor_weights.keys())

    # 归一化权重
    total_weight = sum(factor_weights[f] for f in factor_names if f in factor_weights)
    if total_weight == 0:
        # 回退到等权
        return equal_weight_score(zscores, factor_names)

    scores = {}
    for code, fs in zscores.items():
        weighted_sum = 0.0
        for f in factor_names:
            if f in fs and f in factor_weights:
                weighted_sum += fs[f] * factor_weights[f]
        scores[code] = weighted_sum / total_weight

    return scores
```

**边界情况**：
- 沪深300数据不足20天：默认返回 `bull`（避免新股影响）
- 某因子在某ETF上缺失：`zscore_normalize` 已填充为0，加权计算不受影响
- `market_regime_switch=False`：回退到 `equal_weight_score`，保持向后兼容

---

## 三、架构影响

### 改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `strategy/constraints.py` | 修改 | 默认值 100→30 |
| `strategy/multi_factor.py` | 修改 | 新增流动性指标、回撤止损、市场状态判断 |
| `strategy/scoring.py` | 新增函数 | `weighted_score()` |
| `strategy/optimizer.py` | 修改 | 参数网格新增 `market_regime_switch` |

### 数据流变化

```
原流程:
  next() → _compute_scores() → zscore → equal_weight_score → sector_penalty → top_n

新流程:
  next()
    ├── 检查回撤止损（新增）
    └── _compute_scores()
        ├── 流动性过滤（新增）
        ├── zscore标准化
        ├── 市场状态判断（新增）→ weighted_score
        ├── sector_penalty
        └── top_n
```

---

## 四、测试设计

### 单元测试

**改进1 - 换手率**：
- `test_turnover_limit_30pct`: 验证默认值=30，超限交易被拦截

**改进2 - 流动性过滤**：
- `test_liquidity_filter_low_amount`: 成交额<5000万的ETF被剔除
- `test_liquidity_filter_sufficient`: 成交额≥5000万的ETF保留
- `test_liquidity_filter_insufficient_data`: 数据不足20天时跳过

**改进3 - 回撤止损**：
- `test_drawdown_trigger`: 回撤>15%时触发降仓
- `test_drawdown_no_trigger`: 回撤<15%时不触发
- `test_drawdown_recovery`: 回撤<5%时重置标记
- `test_drawdown_no_repeat`: 已降仓时不重复降仓

**改进4 - 风格轮动**：
- `test_regime_detection_bull`: 沪深300>MA20返回bull
- `test_regime_detection_bear`: 沪深300<MA20返回bear
- `test_weighted_score_bull`: bull模式下动量权重更高
- `test_weighted_score_bear`: bear模式下价值/低波权重更高

### 集成测试

- `test_full_backtest_with_improvements`: 跑2022-2024完整回测，验证：
  - 月度换手率<30%
  - 低流动性ETF未出现在持仓中
  - 回撤止损日志可见
  - 不同市场状态下的因子权重切换可见

---

## 五、风险与缓解

| 风险 | 缓解措施 |
|---|---|
| 换手率限制过严导致调仓不充分 | 起步用30%，如回测显示明显劣化可放宽至50% |
| 流动性过滤剔除过多ETF | 33只ETF池整体流动性较好，预计剔除0-2只 |
| 回撤止损在底部卖出造成损失 | 降仓50%而非清仓，保留反弹空间 |
| 风格轮动判断错误 | 基于沪深300 20日均线，简单可靠，可配置关闭 |

---

## 六、后续优化方向（本次不实现）

1. **红利因子**：将 `etf_valuation` 表的 `dividend_yield` 纳入打分（数据已就绪）
2. **滚动ICIR加权**：用过去12个月ICIR动态调整因子权重
3. **滚动36个月IC检验**：监控因子有效性变化
4. **因子失效监控**：调仓前检查近6个月IC，连续为负则剔除该因子
5. **行业仓位上限**：新增 `max_sector_exposure_pct=15.0` 参数
