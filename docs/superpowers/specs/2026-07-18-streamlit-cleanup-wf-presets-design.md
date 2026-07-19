# Streamlit 清理 + Walk-Forward 多因子预设优化 设计文档

> **目标**：删除 Streamlit 中双动量轮动选项和「优化参数预设」按钮，新建 CLI 脚本通过 Walk-Forward 优化生成5个多因子预设并自动写回 settings.py；更新相关文档。

## 背景

当前 Streamlit UI 同时暴露「双动量轮动」和「多因子轮动」两个策略，以及「🔬 优化参数预设」按钮（在 UI 中跑 Walk-Forward 优化）。多因子优化任务已完成，双动量作为旧策略应下线；UI 中的 Walk-Forward 优化耗时长（1-3分钟）会阻塞 Streamlit 主线程，应改为命令行入口。当前多因子预设（3个）为手写经验值，缺乏回测数据支撑，需用 Walk-Forward 优化生成5个差异化预设替换。

## 架构与文件变更总览

### 涉及文件

| 文件 | 变更类型 | 职责 |
|------|----------|------|
| `scripts/optimize_presets.py` | 新建 | CLI 入口：跑 Walk-Forward 优化，AST 写回 settings.py |
| `strategy/optimizer.py` | 修改 | 新增 `MULTI_FACTOR_PARAM_RANGES` 常量，删除 `DUAL_MOMENTUM_PARAM_RANGES` |
| `config/settings.py` | 修改 | `PARAM_PRESETS` 删除"双动量轮动"键，"多因子轮动"替换为5个WF预设 |
| `presentation/streamlit_app.py` | 修改 | 删除策略下拉、双动量分支、优化按钮、WF报告区 |
| `README.md` | 修改 | 更新策略描述为多因子 + CLI 优化入口 |
| `strategy/dual_momentum.py` | 不变 | 模块文件保留（UI 不再调用，作为参考） |
| `strategy/walk_forward.py` | 不变 | 完全复用，无需修改 |
| `docs/strategy_doc.md` | 不变 | 历史文档保留 |

### 数据流

```
用户执行 CLI:
  scripts/optimize_presets.py --start 2019-01-01 --end 2024-12-31
    ↓
  读取 ETF_UNIVERSE + 全ETF行情数据
    ↓
  generate_walk_forward_presets(data_dict, MULTI_FACTOR_PARAM_RANGES, max_combinations=144)
    ↓ (复用现有5风格预设生成器)
  得到5个预设 + metrics
    ↓
  AST 解析 settings.py，定位 PARAM_PRESETS['多因子轮动']
    ↓
  替换为5个WF预设 + 保留"⚙️ 自定义参数"
    ↓
  写回 settings.py（先备份 .bak）
    ↓
  打印5个预设的回测指标表 + 提示重启 Streamlit
```

### 不变的核心抽象

- `generate_walk_forward_presets` 签名不变，传入不同的 `param_ranges` 即可服务多因子策略
- `MultiFactorStrategy.run_backtest` 签名不变，walk_forward 内部通过 `strategy_module.run_backtest` 调用

---

## CLI 脚本设计（scripts/optimize_presets.py）

### 命令行接口

```bash
.venv/bin/python scripts/optimize_presets.py [OPTIONS]

Options:
  --start DATE       回测起始日期，默认 2019-01-01
  --end DATE         回测结束日期，默认 2024-12-31
  --max-combinations INT  最大参数组合数，默认 144
  --dry-run          仅跑优化打印结果，不写回 settings.py
  --no-backup        跳过 .bak 备份（默认会备份）
  --output FILE      额外输出 JSON 报告到文件
```

### 执行流程

1. **参数解析**：argparse 解析上述选项
2. **初始化数据**：`init_db` → `PriceRepository` 加载 ETF_UNIVERSE 全部33只行情
3. **跑 Walk-Forward**：调用 `generate_walk_forward_presets(data_dict, MULTI_FACTOR_PARAM_RANGES, max_combinations, progress_callback=print_progress)`
   - `progress_callback` 打印 `(current/total) msg` 到 stderr，避免污染 JSON 输出
4. **校验结果**：若 `wf_result['presets']` 为空，报错退出（exit code 1）
5. **打印报告**：tabulate 打印5个预设的回测指标表（预设名/年化/夏普/回撤/窗口CAGR/交易次数）到 stdout
6. **写回 settings.py**（非 `--dry-run` 时）：
   - 备份 `config/settings.py` → `config/settings.py.bak`
   - AST 解析 settings.py，定位 `PARAM_PRESETS` 字典中的 `"多因子轮动"` 键
   - 用5个WF预设 + `{"name": "⚙️ 自定义参数", "params": None}` 构造新列表字面量
   - 用 `ast.unparse`（Python 3.9+）生成新代码段，精确替换原"多因子轮动"列表的源码范围
   - 写回文件，保持其他部分原样
7. **输出 JSON**（`--output` 指定时）：完整 `wf_result` 序列化到文件

### AST 写回关键函数

```python
import ast
from pathlib import Path

def update_presets_in_settings(settings_path: str, new_presets: list):
    """AST 精确替换 PARAM_PRESETS['多因子轮动'] 列表

    Args:
        settings_path: settings.py 路径
        new_presets: [{"name": ..., "params": {...}}, ...]
    """
    src = Path(settings_path).read_text(encoding='utf-8')
    tree = ast.parse(src)

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'PARAM_PRESETS':
                    for key_node, value_node in zip(node.value.keys, node.value.values):
                        if isinstance(key_node, ast.Constant) and key_node.value == "多因子轮动":
                            target_node = value_node
                            break
        if target_node:
            break

    if target_node is None:
        raise RuntimeError("未找到 PARAM_PRESETS['多因子轮动']")

    new_list_src = _build_presets_list_source(new_presets)

    lines = src.splitlines(keepends=True)
    start_line = target_node.lineno - 1
    end_line = target_node.end_lineno
    replaced = src[:sum(len(l) for l in lines[:start_line])] + \
               new_list_src + \
               src[sum(len(l) for l in lines[:end_line]):]

    Path(settings_path).write_text(replaced, encoding='utf-8')


def _build_presets_list_source(presets: list) -> str:
    """构造 PARAM_PRESETS['多因子轮动'] 列表字面量源码"""
    lines = ["["]
    for p in presets:
        name = p['name']
        params = p['params']
        if params is None:
            lines.append(f'    {{"name": "{name}", "params": None}},')
        else:
            params_str = ", ".join(f'"{k}": {v}' for k, v in params.items())
            lines.append(f'    {{"name": "{name}", "params": {{{params_str}}}}},')
    lines.append("]")
    return "\n".join(lines)
```

### 错误处理

- **数据不足**：ETF 行情 < 120 天 → 跳过该 ETF，警告（与 factor_analysis.py 一致）
- **AST 写回失败**：回滚 `.bak`，exit code 2
- **优化无结果**：打印诊断信息（验证窗口数、组合数），exit code 1
- **`ast.unparse` 不可用**（Python < 3.9）：fallback 用字符串拼接（项目要求 3.11+，实际不会触发）

### 输出示例（stdout）

```
============================================================
Walk-Forward 多因子参数优化 (2019-01-01 ~ 2024-12-31)
ETF数: 33 | 参数组合: 144 | 验证窗口: 12
耗时: 87.3s
============================================================

预设名称                   全周期年化(%)  全周期夏普  全周期回撤(%)  窗口CAGR(%)  交易次数
🏆 激进高收益型              8.45        0.62       15.23         22.10        42
🥇 最优风险调整型            6.12        0.58       11.45         18.30        38
🥈 均衡稳健型                5.88        0.55       10.20         17.50        35
🥉 最低回撤型                4.50        0.48        8.30         14.20        28
📊 低频交易型                3.80        0.42       12.10         12.80        15

✅ 已写回 config/settings.py（原文件备份至 config/settings.py.bak）
💡 请重启 Streamlit 使新预设生效
```

---

## Streamlit 清理设计

### 删除清单（按行号倒序，避免删除时行号偏移）

| 行号范围 | 内容 | 删除原因 |
|----------|------|----------|
| 568-595 | `wf_presets = st.session_state.get('wf_presets')` 整段 WF 报告展示区 | WF 报告改由 CLI 输出，UI 不再展示 |
| 506-566 | `if st.session_state.get('optimize_clicked'):` 整段优化执行逻辑 | 优化按钮已删，无触发源 |
| 442-446 | "🔬 优化参数预设" 按钮 + 周围 `st.markdown("---")` | 改为 CLI 入口 |
| 385-389 | `if strategy_type == "双动量轮动":` 参数构建分支 | 双动量分支删除 |
| 356-365 | `if strategy_type == "双动量轮动":` 预设参数读取分支 | 同上 |
| 335-345 | `if strategy_type == "双动量轮动":` 自定义参数滑块分支 | 同上 |
| 314 | `strategy_options = ["双动量轮动", "多因子轮动"]` 和 selectbox | 改为纯文本标题 |
| 25 | `from strategy.walk_forward import generate_walk_forward_presets` | 不再使用 |
| 24 | `from strategy.optimizer import optimize_parameters, DUAL_MOMENTUM_PARAM_RANGES` | 不再使用 |
| 16 | `from strategy import dual_momentum` | UI 不再调用 |
| 63-88 | `run_backtest_for_result` 中的双动量分支和 else 分支 | 简化为只调多因子 |

### 保留并简化的部分

#### 策略参数面板（简化后）

```python
    st.markdown("---")
    st.subheader("⚙️ 策略参数")
    st.caption("多因子轮动策略：动量 + 估值 + 低波动 等权合成")

    dynamic_presets = st.session_state.get('dynamic_presets', {}).get('多因子轮动', [])
    if dynamic_presets:
        preset_options = list(dynamic_presets)
    else:
        presets = PARAM_PRESETS.get('多因子轮动', [])
        preset_options = [
            {"name": p["name"], "params": p["params"], "is_dynamic": False}
            for p in presets
        ]

    preset_names = [p["name"] for p in preset_options]
    preset_select = st.selectbox("参数预设", preset_names, index=0, key="preset_select")
    selected_preset = next((p for p in preset_options if p["name"] == preset_select), None)
    preset_params = selected_preset.get("params") if selected_preset else None
    is_custom = preset_params is None

    if is_custom:
        lookback_momentum = st.slider("动量回看(日)", 10, 120, 60)
        lookback_volatility = st.slider("波动率回看(日)", 10, 120, 60)
        top_n = st.slider("选择标的数", 1, 10, 3)
        rebalance_label = st.selectbox(
            "调仓频率",
            list(REBALANCE_FREQ_OPTIONS.keys()),
            index=2,
        )
        rebalance_days = REBALANCE_FREQ_OPTIONS[rebalance_label]
    else:
        lookback_momentum = preset_params["lookback_momentum"]
        lookback_volatility = preset_params["lookback_volatility"]
        top_n = preset_params["top_n"]
        rebalance_days = preset_params["rebalance_freq"]
        rebalance_label = next((k for k, v in REBALANCE_FREQ_OPTIONS.items() if v == rebalance_days), "20日（月线）")

        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.info(f"动量回看: {lookback_momentum}日")
            st.info(f"波动率回看: {lookback_volatility}日")
        with col_p2:
            st.info(f"选择标的: {top_n}只")
            st.info(f"调仓频率: {rebalance_label}")

    params = {
        "lookback_momentum": lookback_momentum,
        "lookback_volatility": lookback_volatility,
        "top_n": top_n,
        "rebalance_freq": rebalance_days,
    }
```

#### `run_backtest_for_result` 简化

```python
def run_backtest_for_result(selected_codes, start_date, end_date, params, constraints_dict):
    data_dict = {}
    for code in selected_codes:
        prices = price_repo.get_daily_price(code)
        if prices:
            df = pd.DataFrame(prices)
            data_dict[code] = df

    full_params = {**params, 'constraints': constraints_dict}
    full_params['valuation_repo'] = valuation_repo

    from strategy import multi_factor
    result = multi_factor.run_backtest(
        data_dict,
        initial_capital=INITIAL_CAPITAL,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        **full_params,
    )
    return result
```

#### 因子分析按钮保留

「🔬 因子分析」按钮和弹窗逻辑（604-692行）完整保留，与本次清理无关。

#### `dynamic_presets` 缓存的清理

原 `st.session_state['dynamic_presets']['双动量轮动']` 赋值逻辑已删除（在506-566行内）。多因子预设不写入 `dynamic_presets`（因为没有 Streamlit 触发的优化路径），始终读 `PARAM_PRESETS`。`dynamic_presets` 读取逻辑保留但永远为空 list，向后兼容。

### session_state 清理

删除以下 session_state key 的写入（读取保留，未设置时返回 None/False，安全）：
- `optimize_clicked`
- `wf_presets` / `wf_windows` / `wf_elapsed`
- `dynamic_presets['双动量轮动']`

### 副作用：`strategy_type` 变量消失

原代码多处（如第493行 `st.success(f"✅ {strategy_type} 回测完成...")`）引用 `strategy_type`。删除策略下拉后，将这些引用替换为硬编码字符串 `"多因子轮动"`。

---

## settings.py 和 optimizer.py 清理设计

### settings.py 变更（PARAM_PRESETS 部分）

#### CLI 还未运行前的过渡版本

CLI 还未运行，多因子预设暂用占位（标注待 CLI 生成）：

```python
PARAM_PRESETS = {
    "多因子轮动": [
        # 待运行 `scripts/optimize_presets.py` 生成 Walk-Forward 优化预设
        {"name": "⚖️ 等权三因子基线", "params": {
            "lookback_momentum": 60, "lookback_volatility": 60,
            "top_n": 3, "rebalance_freq": 20,
        }},
        {"name": "⚙️ 自定义参数", "params": None},
    ],
}
```

#### CLI 运行后（AST 写回的最终形态）

```python
PARAM_PRESETS = {
    "多因子轮动": [
    {"name": "🏆 激进高收益型", "params": {"lookback_momentum": 20, "lookback_volatility": 60, "top_n": 5, "rebalance_freq": 20}},
    {"name": "🥇 最优风险调整型", "params": {"lookback_momentum": 60, "lookback_volatility": 60, "top_n": 3, "rebalance_freq": 20}},
    {"name": "🥈 均衡稳健型", "params": {"lookback_momentum": 60, "lookback_volatility": 120, "top_n": 3, "rebalance_freq": 20}},
    {"name": "🥉 最低回撤型", "params": {"lookback_momentum": 120, "lookback_volatility": 60, "top_n": 2, "rebalance_freq": 60}},
    {"name": "📊 低频交易型", "params": {"lookback_momentum": 60, "lookback_volatility": 60, "top_n": 2, "rebalance_freq": 60}},
    {"name": "⚙️ 自定义参数", "params": None},
]
}
```

> 实际参数值由 WF 优化结果决定，上面是结构示例。AST 写回会保持 `PARAM_PRESETS = {` 和 `}` 外层结构不变，只替换 `"多因子轮动"` 对应的列表字面量。

### optimizer.py 变更

#### 删除 DUAL_MOMENTUM_PARAM_RANGES

```python
DUAL_MOMENTUM_PARAM_RANGES = {
    'lookback_short': [20, 40, 60, 80],
    'lookback_long': [60, 120, 180, 250],
    'top_n': [1, 2, 3],
    'rebalance_freq': [10, 20, 60],
}
```

#### 新增 MULTI_FACTOR_PARAM_RANGES（替代位置）

```python
MULTI_FACTOR_PARAM_RANGES = {
    'lookback_momentum': [20, 40, 60, 120],
    'lookback_volatility': [20, 60, 120],
    'top_n': [2, 3, 4, 5],
    'rebalance_freq': [10, 20, 60],
}
# 4 × 3 × 4 × 3 = 144 组合，与双动量规模对齐
```

### 参数空间设计依据

| 参数 | 取值 | 理由 |
|------|------|------|
| `lookback_momentum` | [20, 40, 60, 120] | 覆盖月(20)/季(60)/半年(120)三个主流动量周期，40 作为中间过渡 |
| `lookback_volatility` | [20, 60, 120] | 与动量周期对齐，20 日短期波动捕捉风险，120 日长期波动更稳定 |
| `top_n` | [2, 3, 4, 5] | 项目约束 3-5 只持仓，2 加入以测试更集中策略（max_positions=5 仍约束） |
| `rebalance_freq` | [10, 20, 60] | 双周/月/季三档，与 REBALANCE_FREQ_OPTIONS 主流选项对齐 |

### 向后兼容性

- `DUAL_MOMENTUM_PARAM_RANGES` 删除后，唯一引用方是 `streamlit_app.py` 第24行 import（已同步删除）
- `optimize_parameters` 函数本身保留（未来可能用于其他策略的简单网格搜索）
- `MULTI_FACTOR_PARAM_RANGES` 作为新常量，由 `scripts/optimize_presets.py` 引用

---

## README.md 更新设计

### 变更范围

只改动涉及"双动量/估值定投/Walk-Forward 按钮"的描述，其余结构保持不变。

### 具体修改点

#### 1. 项目结构（第30-31行）— 删除估值定投，新增 CLI 脚本

```diff
 ├── strategy/               # 策略层
 │   ├── engine.py          # 策略引擎（因子计算、过滤、评分、排序）
-│   ├── dual_momentum.py   # 双动量ETF轮动策略（含回测函数）
-│   ├── valuation_dca.py   # 估值百分位定投策略（含回测函数）
+│   ├── multi_factor.py    # 多因子轮动策略（动量+估值+低波等权）
+│   ├── factor_analysis.py # 因子有效性检验（RankIC/ICIR/分层回测）
 │   ├── scoring.py         # Z-score标准化 + 等权加权评分
 │   ├── backtest_utils.py  # 回测公共工具函数
+│   ├── optimizer.py       # 参数网格搜索 + 参数范围常量
+│   ├── walk_forward.py    # Walk-Forward 优化引擎（5风格预设生成）
 │   ├── factors/           # 因子库
```

#### 2. scripts/ 段落（第55-56行后）— 新增 optimize_presets.py

```diff
 ├── scripts/               # 脚本
-│   └── verify_factors.py  # 因子验证脚本
+│   ├── verify_factors.py  # 因子验证脚本
+│   └── optimize_presets.py # Walk-Forward 参数优化 CLI（结果写回 settings.py）
```

#### 3. 页面功能表（第88-93行）— 策略描述更新

```diff
 **页面功能：**

 | 页签 | 功能 |
 |------|------|
-| 推荐列表 | Z-score 标准化 + 等权加权评分，ETF 排名 |
-| 因子说明 | 因子方向、标准化方法、加权方式说明 |
-| 回测结果 | 双动量轮动 / 估值定投策略绩效指标 |
-| 净值曲线 | Plotly 交互式净值走势图 |
+| 推荐列表 | Z-score 标准化 + 等权加权评分，ETF 排名 |
+| 因子说明 | 因子方向、标准化方法、加权方式说明 |
+| 回测结果 | 多因子轮动策略绩效指标（动量+估值+低波） |
+| 净值曲线 | Plotly 交互式净值走势图（策略 vs 等权基准） |
+| 因子分析 | RankIC/ICIR/分层回测有效性检验（侧边栏按钮触发） |
```

#### 4. 使用流程（第95-102行）— 新增 CLI 优化入口

```diff
 **使用流程：**

-1. 侧边栏点「拉取ETF列表」→ 选择 ETF 标的
-2. 设置日期范围 → 点「拉取行情数据」
-3. 点「拉取PE历史数据」（获取 5000+ 条指数 PE 历史）
-4. 在「推荐列表」页签点「生成推荐」
-5. 在「回测结果」页签选择策略并点「运行回测」
-6. 在「净值曲线」页签点「生成曲线」
+1. 侧边栏选择 ETF 标的（默认 33 只全池）
+2. 设置日期范围
+3. 选择参数预设（5 个 Walk-Forward 优化预设之一，或自定义）
+4. 点「运行回测」查看绩效指标、净值曲线、交易明细
+5. 点「🔬 因子分析」检验因子有效性
+
+### 参数预设优化（CLI）
+
+预设由 Walk-Forward 优化生成，UI 不提供优化入口。重新生成预设：
+
+```bash
+.venv/bin/python scripts/optimize_presets.py --start 2019-01-01 --end 2024-12-31
+```
+
+- 默认 144 参数组合 × 12 验证窗口，耗时约 1-3 分钟
+- 生成 5 个差异化预设（激进高收益/最优风险调整/均衡稳健/最低回撤/低频交易）
+- 自动写回 `config/settings.py`，原文件备份至 `.bak`
+- 加 `--dry-run` 仅查看结果不写回
+- 加 `--output report.json` 额外输出 JSON 报告
```

#### 5. 架构说明 - 各层职责表（第135-140行）— 策略层描述更新

```diff
 | 层级                | 职责                       | 依赖方向                   |
 | ------------------- | -------------------------- | -------------------------- |
 | presentation 表现层 | Streamlit 页面 + 交互      | 只依赖 service / strategy 层 |
 | service 服务层      | 业务逻辑编排、接口封装     | 依赖 strategy + data 层    |
-| strategy 策略层     | 因子/评分/回测引擎          | 只依赖 data 层（价格数据） |
+| strategy 策略层     | 多因子评分/回测/WF优化引擎  | 只依赖 data 层（价格数据） |
 | data 数据层         | 数据获取 + 存储            | 无上层依赖                 |
```

#### 6. 架构说明 - 四层分层图（第117-130行）— 策略层描述更新

```diff
 ┌─────────────────────────────────────────────────────────┐
 │  表现层 presentation/   Streamlit 页面                  │
-│    推荐列表、因子说明、回测结果、净值曲线                │
+│    推荐列表、因子说明、回测结果、净值曲线、因子分析      │
 ├─────────────────────────────────────────────────────────┤
 │  service 服务层        业务逻辑编排                    │
 │    StrategyService / PortfolioService / DataService    │
 ├─────────────────────────────────────────────────────────┤
-│  策略层 strategy/       因子 → 标准化 → 评分 → 回测     │
-│    动量/波动率/流动性/估值因子；Z-score等权加权          │
-│    双动量轮动 + 估值定投策略（含Backtrader回测）         │
+│  策略层 strategy/       因子 → 标准化 → 评分 → 回测     │
+│    动量/波动率/估值因子；Z-score等权加权                 │
+│    多因子轮动策略（动量+估值+低波）+ Walk-Forward优化    │
 ├─────────────────────────────────────────────────────────┤
```

### 不修改的部分

- 技术栈段落（1-14行）：仍然准确
- 数据层结构（42-53行）：无变化
- 配置层、工具层、测试层结构：无变化
- 快速开始 - 安装依赖（67-73行）：无变化
- 快速开始 - 启动 Streamlit（75-84行）：无变化，端口仍为 8501
- 因子验证脚本说明（104-110行）：无变化
- 运行测试（142-146行）：无变化
- 扩展方向（148-167行）：无变化

---

## 测试策略

### 测试文件清单

| 文件 | 类型 | 测试数 | 职责 |
|------|------|--------|------|
| `tests/test_optimize_presets.py` | 新建 | 5 | CLI 脚本核心函数（AST 写回、预设列表生成） |
| `tests/test_streamlit_cleanup.py` | 新建 | 3 | 语法检查 + 残留引用扫描 |
| 现有测试 | 修改 | - | 移除对已删除常量的引用 |

### test_optimize_presets.py 详细测试

```python
"""optimize_presets CLI 脚本测试"""
import sys
import ast
import tempfile
import shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


def test_build_presets_list_source_with_params():
    """构造预设列表源码 - 含参数"""
    from scripts.optimize_presets import _build_presets_list_source
    presets = [
        {"name": "🏆 激进高收益型", "params": {"lookback_momentum": 20, "top_n": 3}},
        {"name": "⚙️ 自定义参数", "params": None},
    ]
    src = _build_presets_list_source(presets)
    tree = ast.parse(src)
    assert isinstance(tree.body[0], ast.List)
    assert len(tree.body[0].elts) == 2
    assert "🏆 激进高收益型" in src
    assert "lookback_momentum" in src
    assert "None" in src


def test_update_presets_in_settings_replaces_correctly():
    """AST 精确替换 PARAM_PRESETS['多因子轮动']"""
    from scripts.optimize_presets import update_presets_in_settings

    tmpdir = tempfile.mkdtemp()
    settings_path = Path(tmpdir) / "settings.py"
    original = '''PARAM_PRESETS = {
    "多因子轮动": [
        {"name": "旧预设", "params": {"lookback_momentum": 60}},
        {"name": "⚙️ 自定义参数", "params": None},
    ],
}

OTHER_CONST = 42
'''
    settings_path.write_text(original, encoding='utf-8')

    new_presets = [
        {"name": "🏆 新预设", "params": {"lookback_momentum": 20, "lookback_volatility": 60, "top_n": 5, "rebalance_freq": 20}},
        {"name": "⚙️ 自定义参数", "params": None},
    ]
    update_presets_in_settings(str(settings_path), new_presets)

    new_src = settings_path.read_text(encoding='utf-8')
    tree = ast.parse(new_src)

    found_other = False
    found_presets = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == 'OTHER_CONST':
                    found_other = True
                elif node.targets[0].id == 'PARAM_PRESETS':
                    found_presets = True
                    value_node = node.value
                    assert isinstance(value_node, ast.Dict)
                    key = value_node.keys[0]
                    assert isinstance(key, ast.Constant) and key.value == "多因子轮动"
                    list_node = value_node.values[0]
                    assert len(list_node.elts) == 2
    assert found_other, "OTHER_CONST 应保留"
    assert found_presets, "PARAM_PRESETS 应存在"
    assert "旧预设" not in new_src
    assert "🏆 新预设" in new_src

    shutil.rmtree(tmpdir)


def test_update_presets_rollback_on_failure():
    """AST 写回失败时回滚 .bak
    
    传入不可序列化的 object() 作为 params，触发 _build_presets_list_source
    的 f-string 拼接抛 TypeError，验证原文件保持不变。
    """
    from scripts.optimize_presets import update_presets_in_settings

    tmpdir = tempfile.mkdtemp()
    settings_path = Path(tmpdir) / "settings.py"
    original = 'PARAM_PRESETS = {"多因子轮动": []}\n'
    settings_path.write_text(original, encoding='utf-8')

    with pytest.raises(Exception):
        update_presets_in_settings(str(settings_path), [{"name": "bad", "params": object()}])

    assert settings_path.read_text(encoding='utf-8') == original
    shutil.rmtree(tmpdir)


def test_multi_factor_param_ranges_exists():
    """MULTI_FACTOR_PARAM_RANGES 常量存在且组合数为144"""
    from strategy.optimizer import MULTI_FACTOR_PARAM_RANGES
    values = list(MULTI_FACTOR_PARAM_RANGES.values())
    total = 1
    for v in values:
        total *= len(v)
    assert total == 144, f"期望144组合，实际{total}"


def test_dual_momentum_param_ranges_removed():
    """DUAL_MOMENTUM_PARAM_RANGES 已删除"""
    from strategy import optimizer
    assert not hasattr(optimizer, 'DUAL_MOMENTUM_PARAM_RANGES'), \
        "DUAL_MOMENTUM_PARAM_RANGES 应已删除"
```

### test_streamlit_cleanup.py 详细测试

```python
"""Streamlit 清理验证测试"""
import sys
import ast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_streamlit_app_syntax_valid():
    """streamlit_app.py 语法正确"""
    src = Path('presentation/streamlit_app.py').read_text(encoding='utf-8')
    ast.parse(src)


def test_streamlit_app_no_dual_momentum_references():
    """streamlit_app.py 不再引用双动量"""
    src = Path('presentation/streamlit_app.py').read_text(encoding='utf-8')
    forbidden = [
        'dual_momentum',
        '双动量轮动',
        'DUAL_MOMENTUM_PARAM_RANGES',
        'generate_walk_forward_presets',
        'optimize_clicked',
        'wf_presets',
    ]
    found = [f for f in forbidden if f in src]
    assert not found, f"streamlit_app.py 仍有残留引用: {found}"


def test_settings_no_dual_momentum_preset():
    """settings.py 中 PARAM_PRESETS 不含双动量轮动键"""
    from config.settings import PARAM_PRESETS
    assert '双动量轮动' not in PARAM_PRESETS, "PARAM_PRESETS 仍含双动量轮动键"
    assert '多因子轮动' in PARAM_PRESETS, "PARAM_PRESETS 应含多因子轮动键"
```

### 现有测试的修改

- `test_multi_factor.py` — 无需修改（不依赖 Streamlit）
- `test_constraints.py` — 无需修改（不依赖策略选择器）
- `test_factor_analysis.py` — 无需修改（独立）
- `test_dual_momentum_cash.py` — 无需修改（直接 import `strategy.dual_momentum`，模块文件保留）
- 历史失败的 `test_strategy_engine.py` / `test_strategy_factors.py` — 无需修改（与本次清理无关）

### 测试执行命令

```bash
.venv/bin/python -m pytest tests/test_optimize_presets.py tests/test_streamlit_cleanup.py -v
.venv/bin/python -m pytest tests/ -v --ignore=tests/test_run_strategy.py --ignore=tests/test_web_templates.py
```

### 预期测试结果

- 新增 8 个测试全部通过
- 既有 28 个测试（constraints 20 + factor_analysis 5 + multi_factor 3）继续通过
- `test_dual_momentum_cash.py` 独立继续通过（直接 import `strategy.dual_momentum`，模块文件保留）
- 历史遗留 3 个失败（test_strategy_engine/test_strategy_factors）不变

### 测试覆盖度总结

| 验证项 | 测试方法 |
|--------|----------|
| AST 写回正确性 | `test_update_presets_in_settings_replaces_correctly` |
| AST 写回失败回滚 | `test_update_presets_rollback_on_failure` |
| 预设列表源码生成 | `test_build_presets_list_source_with_params` |
| 多因子参数范围 | `test_multi_factor_param_ranges_exists` |
| 双动量常量已删 | `test_dual_momentum_param_ranges_removed` |
| Streamlit 语法正确 | `test_streamlit_app_syntax_valid` |
| Streamlit 无残留引用 | `test_streamlit_app_no_dual_momentum_references` |
| settings 双动量已删 | `test_settings_no_dual_momentum_preset` |
