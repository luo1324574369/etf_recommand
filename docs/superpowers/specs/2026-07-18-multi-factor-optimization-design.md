# A股因子优化设计：多因子轮动策略 + 因子有效性检验

## 背景与目标

当前项目核心策略为双动量轮动（dual_momentum），仅依赖动量因子，在A股震荡市表现疲软。根据A股因子投资理论，需要：

1. **多因子融合**：从纯动量升级为"动量+估值+低波动"三因子，适配A股"动量弱、反转强、价值稳健"的特性
2. **因子有效性检验**：用RankIC/ICIR/分层单调性验证因子是否真的有效，而非盲目加权
3. **风格分散约束**：避免策略全仓押注单一行业风格

## 设计原则

- **不动dual_momentum**：保持现有Walk-Forward优化结果不变，向后兼容
- **复用现有能力**：scoring.py已支持多因子计算和合成，直接调用
- **因子检验独立**：可命令行运行，也可被Streamlit调用
- **等权基线起步**：遵循A股因子理论"新手从等权基线起步，避免ICIR过拟合"

## 整体架构

### 模块依赖关系

```
presentation/streamlit_app.py
├─ 策略下拉新增「多因子轮动」
└─ 侧边栏新增「🔬 因子分析」按钮 → 弹窗展示IC/ICIR报告
       │                          │
       ▼                          ▼
strategy/multi_factor.py    strategy/factor_analysis.py
(多因子策略)                 (检验工具)
│ - 动量0.33                 │ - RankIC
│ - 估值0.33                 │ - ICIR
│ - 低波0.33                 │ - 分层单调性
│ - 风格分散约束              │ - 月度IC序列
└───────┬──────────────────────┘
        │ 共享依赖
        ▼
strategy/scoring.py (现有，已支持多因子)
├─ compute_all_factors()
├─ zscore_normalize()
└─ equal_weight_score()
        │
        ▼
strategy/constraints.py (修改)
└─ 新增: max_per_sector 风格分散约束
```

### 文件改动清单

| 文件 | 类型 | 职责 | 改动量 |
|------|------|------|--------|
| `strategy/factor_analysis.py` | 新建 | 因子有效性检验工具 | ~200行 |
| `strategy/multi_factor.py` | 新建 | 多因子轮动策略 | ~250行 |
| `strategy/constraints.py` | 修改 | 新增`max_per_sector` | ~30行 |
| `presentation/streamlit_app.py` | 修改 | 策略下拉+因子分析弹窗+风格滑块 | ~80行 |
| `config/settings.py` | 修改 | 新增多因子预设 | ~20行 |
| `tests/test_factor_analysis.py` | 新建 | 因子检验测试 | ~80行 |
| `tests/test_multi_factor.py` | 新建 | 多因子策略测试 | ~80行 |
| `tests/test_constraints.py` | 修改 | 追加风格分散测试 | ~40行 |

## 第1部分：因子有效性检验模块

### 模块职责

`strategy/factor_analysis.py` 提供3类检验指标，输入是历史数据，输出是检验报告。

### 核心函数签名

```python
def compute_rank_ic(
    factor_values: pd.DataFrame,  # columns: ['date', 'code', 'factor1', 'factor2', ...]
    forward_returns: pd.DataFrame,  # columns: ['date', 'code', 'forward_return']
    factor_names: list[str],
    method: str = 'spearman',  # 'spearman' (RankIC) or 'pearson' (IC)
) -> pd.DataFrame:
    """计算月度截面RankIC序列
    返回: DataFrame, columns=['date', 'factor_name', 'ic']
    """

def compute_icir(ic_series: pd.Series) -> dict:
    """计算单因子的ICIR
    返回: {'ic_mean': float, 'ic_std': float, 'icir': float, 
           'ic_positive_ratio': float, 'ic_t_stat': float}
    """

def stratified_backtest(
    factor_values: pd.DataFrame,
    forward_returns: pd.DataFrame,
    factor_name: str,
    n_groups: int = 5,
) -> pd.DataFrame:
    """分层回测：按因子值分5组，计算各组未来收益
    返回: DataFrame, columns=['date', 'group', 'avg_return']
    group=1是因子值最低组，group=5是最高组
    """

def analyze_factor(
    code: str,
    prices: list[dict],
    pe_history: list[dict] = None,
    factor_names: list[str] = None,
    forward_period: int = 20,
) -> dict:
    """单ETF全量因子检验（供Streamlit调用）
    返回: {
        'factor_name': {
            'ic_series': [...],
            'icir': {...},
            'stratified': {...},
            'verdict': '有效' | '弱有效' | '无效'
        }
    }
    """

def analyze_all_etfs(
    etf_codes: list[str],
    price_repo,
    valuation_repo,
    start_date: str,
    end_date: str,
    factor_names: list[str] = None,
    forward_period: int = 20,
) -> dict:
    """全ETF池因子检验汇总
    返回: {factor_name: {ic_mean, icir, ic_positive_ratio, monotonicity, verdict, ic_series, stratified}}
    """
```

### 有效性判定标准（A股ETF适配版）

基于A股因子理论，但适配ETF特性（样本量小、无法行业中性化）：

| 指标 | 有效 | 弱有效 | 无效 |
|------|------|--------|------|
| RankIC均值绝对值 | ≥0.05 | 0.03-0.05 | <0.03 |
| ICIR | ≥0.3 | 0.1-0.3 | <0.1 |
| IC正比例 | ≥60% | 50-60% | <50% |
| 分层单调性 | 组5-组1显著且单调 | 方向正确但不严格单调 | 无单调性 |

判定逻辑：4个指标中**≥2个达到"有效"**判为有效，**≥2个达到"弱有效+"**判为弱有效，否则无效。

### 数据流

```
输入: ETF历史行情 + PE历史 + 因子列表
    ↓
1. 逐日计算因子值 (复用 compute_all_factors)
    ↓
2. 计算前瞻收益 forward_return (T+20日收益)
    ↓
3. 按月度截面计算 RankIC (spearman相关)
    ↓
4. 汇总: IC均值、IC标准差、ICIR、IC正比例
    ↓
5. 分层回测: 按因子值分5组，计算各组平均收益
    ↓
6. 输出: IC时间序列 + ICIR指标 + 分层收益 + 有效性判定
```

### 前瞻收益计算

```python
def _compute_forward_returns(prices: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算每只ETF每个日期的period日前瞻收益"""
    df = prices.sort_values(['code', 'trade_date'])
    df['future_close'] = df.groupby('code')['close'].shift(-period)
    df['forward_return'] = (df['future_close'] - df['close']) / df['close']
    return df[['trade_date', 'code', 'forward_return']].dropna()
```

### 命令行独立运行

```bash
# 分析所有ETF的动量因子有效性
.venv/bin/python -m strategy.factor_analysis --factor momentum_60d --start 2019-01-01 --end 2024-12-31

# 输出JSON报告
.venv/bin/python -m strategy.factor_analysis --all --output report.json
```

## 第2部分：多因子轮动策略

### 策略职责

`strategy/multi_factor.py` 实现等权三因子轮动：动量 + 估值 + 低波动，复用 `scoring.py` 的因子计算和合成能力。

### 策略参数

```python
class MultiFactorStrategy(bt.Strategy):
    params = (
        ('lookback_momentum', 60),      # 动量回看周期
        ('lookback_volatility', 60),    # 波动率回看周期
        ('top_n', 3),                   # 选股数量
        ('rebalance_freq', 20),         # 调仓频率(日)
        ('commission_rate', 0.0003),
        ('start_date', None),
        ('constraints', None),
        ('factor_weights', None),       # 因子权重，None=等权
    )
```

**关键设计**：`factor_weights=None` 默认等权（动量0.33+估值0.33+低波0.33），支持后续扩展为自定义权重。

### 因子选择与方向

复用 `scoring.py` 的因子定义：

| 因子 | 字段名 | 方向 | 说明 |
|------|--------|------|------|
| 动量 | `momentum_60d` | +1 | 60日收益率，越高越好 |
| 估值 | `pe_percentile` | -1 | PE历史百分位，越低越便宜越好 |
| 低波动 | `volatility_60d` | -1 | 60日波动率，越低越好 |

`FACTOR_DIRECTIONS` 已在scoring.py中定义，zscore_normalize会自动按方向调整。

### 调仓流程（三阶段，复用dual_momentum的修复）

```
┌─ 阶段1：卖出 ─────────────────────────────────────────┐
│ 1a. 清仓：不在新top_n的持仓 → 全部卖出               │
│ 1b. 减仓：仍在top_n但超max_single_mv×1.05 → 卖多余   │
│ 1c. 风格分散检查：同sector超过max_per_sector → 卖出   │
│     多余的同sector持仓（按因子得分从低到高卖）        │
│ → 累计 pending_sell_amounts                          │
└───────────────────────────────────────────────────────┘
                       ↓
┌─ 阶段2：现金感知买入 ─────────────────────────────────┐
│ 2a. effective_cash = broker.get_cash() + pending_sells│
│ 2b. 总仓位上限检查                                    │
│ 2c. 风格分散检查：买入前检查同sector是否已达上限       │
│ 2d. 单笔预算 = min(单仓缺口, effective_cash)          │
│ 2e. 按比例缩减target_size                             │
│ 2f. 扣减effective_cash                                │
└───────────────────────────────────────────────────────┘
                       ↓
┌─ 阶段3：交易日志 ─────────────────────────────────────┐
│ 复用dual_momentum的_log_trade逻辑                     │
│ 调仓原因改为多因子得分描述                             │
└───────────────────────────────────────────────────────┘
```

### 因子计算与选股逻辑

```python
def _compute_scores(self):
    """计算所有ETF的多因子综合得分"""
    etf_factors = {}
    for d in self.datas:
        code = d._name
        prices = self._extract_prices(d)
        if len(prices) < 60:
            continue
        
        pe_pct = self._get_pe_percentile(code)
        factors = compute_all_factors(code, prices, pe_percentile=pe_pct)
        if factors:
            etf_factors[code] = factors
    
    zscores = zscore_normalize(etf_factors, factor_names=['momentum_60d', 'pe_percentile', 'volatility_60d'])
    scores = equal_weight_score(zscores, factor_names=['momentum_60d', 'pe_percentile', 'volatility_60d'])
    
    sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [code for code, score in sorted_codes[:self.p.top_n]]
    
    return selected, scores
```

### PE百分位获取

从数据库读取，复用 `valuation_repo.py`：

```python
def _get_pe_percentile(self, code: str) -> float:
    """获取ETF当前PE历史百分位"""
    pe_history = self.valuation_repo.get_pe_history(code)
    if not pe_history:
        return None
    current_pe = pe_history[-1].get('pe')
    if current_pe is None or current_pe <= 0:
        return None
    all_pes = [h['pe'] for h in pe_history if h.get('pe') and h['pe'] > 0]
    if not all_pes:
        return None
    rank = sum(1 for pe in all_pes if pe <= current_pe)
    return rank / len(all_pes) * 100
```

### 调仓原因描述

交易日志的`reason`字段改为多因子得分描述：

```python
# 买入原因
reason = f"多因子排名第{rank}/{total_n}，综合得分{score:.2f}，动量{momentum:.1f}%，PE百分位{pe_pct:.0f}%，波动率{vol:.1f}%"

# 卖出原因
reason = f"多因子排名第{rank}/{total_n}，调出持仓（综合得分{score:.2f}）"
```

### 预热期处理

复用dual_momentum的预热机制：
- `lookback_volatility=60` 需要60天历史数据
- `day_count` 初始化为 `rebalance_freq - 1`，首日即调仓
- `start_date` 之前的bar跳过交易但计算指标

### run_backtest / get_nav_curve

```python
def run_backtest(data_dict, initial_capital=1000000, commission_rate=0.0003,
                 start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import run_backtest as _run
    return _run(MultiFactorStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)

def get_nav_curve(data_dict, initial_capital=1000000, commission_rate=0.0003,
                  start_date=None, end_date=None, **kwargs):
    from strategy.backtest_utils import get_nav_curve as _nav
    return _nav(MultiFactorStrategy, data_dict, initial_capital, commission_rate,
                start_date, end_date, **kwargs)
```

### 与dual_momentum的对比

| 维度 | dual_momentum | multi_factor |
|------|--------------|--------------|
| 因子 | 动量（短+长各50%） | 动量+估值+低波（等权） |
| 选股 | 动量得分top_n | 多因子综合得分top_n |
| 信号过滤 | `min_momentum > 0` | 无（综合得分无自然下限） |
| 调仓原因 | "双动量排名第X" | "多因子排名第X，动量Y%，PE百分位Z%，波动率W%" |
| 风格分散 | 无 | 有（max_per_sector约束） |

## 第3部分：风格分散约束

### 约束参数

在 `strategy/constraints.py` 的 `StrategyConstraints` 新增 `max_per_sector` 参数。

```python
class StrategyConstraints:
    def __init__(
        self,
        long_only: bool = True,
        max_positions: int = 5,
        min_positions: int = 0,
        max_position_pct: float = 40.0,
        max_total_exposure_pct: float = 95.0,
        slippage_rate: float = 0.1,
        t_plus_one: bool = True,
        min_trade_amount: float = 5000.0,
        max_monthly_turnover: float = 100.0,
        max_per_sector: int = 0,  # 新增：单一风格最大持仓数，0=不限制
    ):
```

### sector信息传递

ETF的sector信息来自 `config/settings.py` 的 `ETF_UNIVERSE`。约束模块本身不依赖config，通过参数注入：

```python
def can_buy(
    self,
    code: str,
    price: float,
    amount: float,
    current_positions: Dict[str, float],
    total_value: float,
    current_date: date,
    effective_cash: float = None,
    code_to_sector: Dict[str, str] = None,  # 新增：{code: sector}映射
) -> Tuple[bool, str]:
    # ... 原有检查 ...
    
    # 新增：风格分散检查
    if self.max_per_sector > 0 and code_to_sector:
        target_sector = code_to_sector.get(code)
        if target_sector:
            current_sector_count = sum(
                1 for c, mv in current_positions.items()
                if mv > 0 and code_to_sector.get(c) == target_sector
            )
            # 新标的（当前未持仓）才检查，已有持仓的加仓不限制
            if code not in current_positions or current_positions.get(code, 0) <= 0:
                if current_sector_count >= self.max_per_sector:
                    return False, f"{target_sector}风格持仓{current_sector_count}只已达上限{self.max_per_sector}"
    
    return True, ""
```

### 卖出时的风格分散处理

风格分散不需要在 `can_sell` 中阻止卖出（卖出只会减少同风格持仓数，不会增加）。但在阶段1c（减仓）中需要处理：**同sector超过max_per_sector时，卖出多余的同sector持仓**。

这个逻辑放在策略层而非约束层，因为涉及"选哪些卖"的决策：

```python
# multi_factor.py 阶段1c：风格分散减仓
if self.constraints.max_per_sector > 0 and code_to_sector:
    sector_holdings = {}  # {sector: [(code, score, position_mv), ...]}
    for d in self.datas:
        pos = self.getposition(d)
        if pos.size > 0:
            sector = code_to_sector.get(d._name, '未知')
            sector_holdings.setdefault(sector, []).append(
                (d._name, scores.get(d._name, 0), pos.size * d.close[0])
            )
    
    for sector, holdings in sector_holdings.items():
        if len(holdings) > self.constraints.max_per_sector:
            # 按因子得分从低到高排序，卖出得分最低的
            holdings.sort(key=lambda x: x[1])
            num_to_sell = len(holdings) - self.constraints.max_per_sector
            for code, score, mv in holdings[:num_to_sell]:
                d = self.getdatabyname(code)
                # 执行卖出...
```

### code_to_sector构建

策略初始化时从 `ETF_UNIVERSE` 构建：

```python
# multi_factor.py __init__
from config.settings import ETF_UNIVERSE
self.code_to_sector = {e['code']: e['sector'] for e in ETF_UNIVERSE}
```

### 约束生效场景示例

假设 `max_per_sector=2`，当前持仓3只科技ETF（芯片、科技、半导体）：

| 场景 | 行为 | 原因 |
|------|------|------|
| 买入第4只科技ETF | ❌ 拒绝 | 科技风格已达2只上限 |
| 加仓已持有的科技ETF | ✅ 允许 | 已持仓，不算新风格敞口 |
| 调仓日时科技持仓3只 | 卖出得分最低的1只 | 阶段1c强制减仓 |
| 卖出1只科技ETF后买入非科技 | ✅ 允许 | 非科技风格未达上限 |

### 向后兼容

- `max_per_sector=0` 默认不限制，dual_momentum等现有策略不受影响
- `code_to_sector=None` 时跳过风格检查，避免老调用报错
- 新参数有默认值，现有测试不受影响

## 第4部分：Streamlit集成

### 策略选择器恢复

当前 `streamlit_app.py` 硬编码了 `strategy_type = "双动量轮动"`。恢复为下拉选择器：

```python
strategy_options = ["双动量轮动", "多因子轮动"]
strategy_type = st.selectbox("策略类型", strategy_options, index=0, key="strategy_select")
```

### 策略参数动态切换

不同策略的参数不同，需根据 `strategy_type` 显示不同参数面板：

```python
if strategy_type == "双动量轮动":
    # 现有逻辑：lookback_short, lookback_long, top_n, rebalance_freq
    # 预设来自 PARAM_PRESETS["双动量轮动"]
elif strategy_type == "多因子轮动":
    # 新逻辑：lookback_momentum, lookback_volatility, top_n, rebalance_freq
    # 预设来自 PARAM_PRESETS["多因子轮动"]
```

### 多因子预设配置

在 `config/settings.py` 的 `PARAM_PRESETS` 新增：

```python
PARAM_PRESETS = {
    "双动量轮动": [...],  # 现有5个Walk-Forward预设
    "多因子轮动": [
        {"name": "⚖️ 等权三因子基线", "params": {
            "lookback_momentum": 60, "lookback_volatility": 60,
            "top_n": 3, "rebalance_freq": 20,
        }},
        {"name": "🛡️ 防御型(低波优先)", "params": {
            "lookback_momentum": 120, "lookback_volatility": 60,
            "top_n": 2, "rebalance_freq": 60,
        }},
        {"name": "📈 进攻型(动量优先)", "params": {
            "lookback_momentum": 20, "lookback_volatility": 120,
            "top_n": 4, "rebalance_freq": 10,
        }},
        {"name": "⚙️ 自定义参数", "params": None},
    ],
}
```

**说明**：当前先用经验预设，后续可对多因子策略也跑Walk-Forward优化生成数据驱动预设。

### 回测分发逻辑

修改 `run_backtest_for_result` 函数，根据策略类型分发：

```python
def run_backtest_for_result(selected_codes, start_date, end_date, strategy_type, params, constraints_dict):
    data_dict = {}
    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            data_dict[code] = pd.DataFrame(prices)

    full_params = {**params, 'constraints': constraints_dict}

    if strategy_type == "双动量轮动":
        from strategy import dual_momentum
        result = dual_momentum.run_backtest(
            data_dict, initial_capital=INITIAL_CAPITAL,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            **full_params,
        )
    elif strategy_type == "多因子轮动":
        from strategy import multi_factor
        full_params['constraints'] = {
            **constraints_dict,
            'code_to_sector': {e['code']: e['sector'] for e in ETF_UNIVERSE},
        }
        result = multi_factor.run_backtest(
            data_dict, initial_capital=INITIAL_CAPITAL,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            **full_params,
        )
    return result
```

### 因子分析弹窗

侧边栏新增「🔬 因子分析」按钮（独立于回测，触发因子检验）：

```python
if st.button("🔬 因子分析", use_container_width=True,
             help="检验各因子在ETF池中的有效性（RankIC/ICIR/分层回测）"):
    st.session_state['factor_analysis_clicked'] = True

if st.session_state.get('factor_analysis_clicked'):
    @st.dialog("因子有效性分析", width="large")
    def show_factor_analysis():
        from strategy.factor_analysis import analyze_all_etfs
        with st.spinner("正在计算因子有效性..."):
            report = analyze_all_etfs(
                etf_codes=[e['code'] for e in ETF_UNIVERSE],
                price_repo=price_repo,
                valuation_repo=valuation_repo,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
            )

        st.markdown(f"**分析区间**: {start_date} ~ {end_date} | **ETF数**: {len(ETF_UNIVERSE)}")

        # 因子汇总表
        summary_rows = []
        for factor, metrics in report.items():
            summary_rows.append({
                '因子': FACTOR_LABELS.get(factor, factor),
                'RankIC均值': f"{metrics['ic_mean']:.4f}",
                'ICIR': f"{metrics['icir']:.3f}",
                'IC正比例': f"{metrics['ic_positive_ratio']:.1%}",
                '分层单调性': metrics['monotonicity'],
                '判定': metrics['verdict'],
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        # 因子切换 + IC时间序列 + 分层回测图
        factor_options = list(report.keys())
        selected_factor = st.selectbox("选择因子查看详情", factor_options)
        if selected_factor:
            m = report[selected_factor]
            ic_df = pd.DataFrame(m['ic_series'])
            fig_ic = go.Figure()
            fig_ic.add_bar(x=ic_df['date'], y=ic_df['ic'], name='月度IC')
            fig_ic.add_trace(go.Scatter(
                x=ic_df['date'], y=ic_df['ic'].cumsum(),
                name='累计IC', yaxis='y2', line=dict(color='red')
            ))
            st.plotly_chart(fig_ic, use_container_width=True)

            strat_df = pd.DataFrame(m['stratified'])
            fig_strat = px.line(strat_df, x='date', y='cum_return', color='group',
                                title=f"{selected_factor} 分层回测")
            st.plotly_chart(fig_strat, use_container_width=True)

    show_factor_analysis()
```

### 单一风格上限滑块

在「🔒 风控约束」区域新增：

```python
max_per_sector = st.slider("单一风格上限", 0, 10, 2, 
                           help="同一sector(如科技、医药)最多持仓数，0=不限制")

constraints_dict = {
    ...  # 现有约束
    "max_per_sector": max_per_sector,
}
```

### 多因子策略的调仓原因展示

交易详情表的「调仓原因」列会自动显示多因子得分描述，无需改 `build_trade_table`。Streamlit直接读取 `result['trade_list']` 中的 `reason` 字段。

## 第5部分：测试策略

### 测试文件清单

| 文件 | 职责 | 测试数 |
|------|------|--------|
| `tests/test_factor_analysis.py` | 因子检验工具 | 5个 |
| `tests/test_multi_factor.py` | 多因子策略 | 4个 |
| `tests/test_constraints.py` | 追加风格分散约束测试 | +3个 |

### 因子检验测试

```python
def test_compute_rank_ic():
    """测试RankIC计算
    构造已知因子值和前瞻收益，验证spearman相关系数
    - 因子值与收益完全正相关 → IC=1.0
    - 因子值与收益完全负相关 → IC=-1.0
    - 随机无相关 → |IC|<0.3
    """

def test_compute_icir():
    """测试ICIR计算
    IC序列 [0.1, 0.2, 0.15, 0.05, 0.1]
    IC均值=0.12, IC标准差=0.055, ICIR=2.18
    """

def test_stratified_backtest():
    """测试分层回测
    构造单调递增的因子-收益关系，验证5组收益单调
    """

def test_analyze_factor_verdict():
    """测试有效性判定
    - 强因子（IC=0.08, ICIR=0.5）→ '有效'
    - 弱因子（IC=0.04, ICIR=0.2）→ '弱有效'
    - 无效因子（IC=0.01, ICIR=0.05）→ '无效'
    """

def test_forward_returns():
    """测试前瞻收益计算
    10个交易日的价格序列，period=3
    验证第8日的forward_return = (close[10]-close[8])/close[8]
    """
```

### 多因子策略测试

```python
def test_multi_factor_basic():
    """基础回测：3只ETF，2023-2024，验证不崩溃
    - 返回result包含必要字段: trade_list, nav_df, metrics
    - 交易记录数 > 0
    """

def test_multi_factor_style_constraint():
    """风格分散约束生效
    33只ETF全池，max_per_sector=1
    - 任意时刻同sector持仓 ≤ 1
    - 验证trade_list中无违反风格约束的买入
    """

def test_multi_factor_cash_management():
    """现金管理：5只ETF，max_position_pct=40%
    - 任意调仓日总仓位 ≤ 95%
    - 无现金不足导致的失败订单
    - 每笔交易日志的amount ≤ 当时的effective_cash
    """

def test_multi_factor_vs_dual_momentum():
    """多因子 vs 双动量对比
    同区间同ETF池，验证多因子策略：
    - 在震荡市(2022-2024)回撤不大于双动量
    - 交易记录的reason包含"多因子排名"
    """
```

### 风格分散约束测试（追加到test_constraints.py）

```python
def test_can_buy_sector_limit():
    """买入时风格分散检查
    - max_per_sector=2，科技风格已持仓2只
    - 买入第3只科技ETF → 拒绝
    - 买入非科技ETF → 允许
    """

def test_can_buy_sector_add_position():
    """已持仓的加仓不受风格限制
    - max_per_sector=1，科技风格持仓1只（芯片ETF）
    - 加仓芯片ETF → 允许（不算新风格敞口）
    """

def test_can_sell_no_sector_check():
    """卖出不做风格分散检查
    - 卖出只会减少同风格持仓数，不应被风格约束阻止
    """
```

### 测试数据策略

- **因子检验测试**：用合成数据（已知IC=1.0/-1.0/0.0），验证计算正确性
- **多因子策略测试**：用真实数据库数据（510300/510500/512480），验证端到端流程
- **风格约束测试**：用mock的current_positions和code_to_sector，纯单元测试

### 回归测试

完成所有新测试后，运行全量测试确保不破坏现有功能：

```bash
.venv/bin/python -m pytest tests/ -v
```

预期：所有测试通过（现有24个 + 新增12个 = 36个）。

## 成功标准

1. **因子检验工具可独立运行**：命令行 `python -m strategy.factor_analysis --factor momentum_60d` 输出IC/ICIR报告
2. **多因子策略回测正常**：Streamlit选择「多因子轮动」策略，2023-2024回测有交易记录且符合约束
3. **风格分散约束生效**：`max_per_sector=2` 时，任意调仓日同sector持仓 ≤ 2
4. **因子分析弹窗可用**：点击「🔬 因子分析」按钮，展示IC/ICIR/分层回测图表
5. **现有dual_momentum不受影响**：所有现有测试通过，Walk-Forward预设正常工作
6. **全量测试通过**：36个测试全部通过
