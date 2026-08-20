# ETF 量化推荐系统

一个基于 Python 的 ETF 量化选股系统，Streamlit 交互式页面，支持多因子评分、策略回测和净值曲线展示。

## 技术栈

- **Python 3.11+** - 核心开发语言
- **SQLite** - 轻量级本地数据库，存储 ETF 基础信息、行情和估值数据
- **AkShare** - 开源财经数据接口，获取 ETF 行情和指数 PE 历史数据
- **Tushare Pro** - 付费金融数据接口，配置 token 后作为 ETF 日线主源，并与 AkShare 交叉校验
- **Backtrader** - 量化回测框架，支持策略历史回测和绩效分析
- **Streamlit** - 交互式数据可视化页面
- **Plotly** - 净值曲线等图表绘制
- **pandas** - 数据处理和分析库

## 项目结构（四层分层架构）

```
etf_recommand/
├── presentation/            # 表现层（Streamlit 页面）
│   ├── streamlit_app.py   # Streamlit 量化策略页面（推荐列表/回测/净值曲线）
│   ├── app.py              # 历史 Flask 入口兼容层
│   └── cli/run_strategy.py # service 层信号运行入口
│
├── service/                # 服务层（业务逻辑编排）
│   ├── strategy_service.py # 策略运行、信号查询
│   ├── application_service.py # 统一应用编排与因子快照
│   ├── portfolio_service.py # 账户、买卖、持仓盈亏计算
│   └── data_service.py    # ETF 详情、价格、因子计算、数据更新
│
├── strategy/               # 策略层
│   ├── engine.py          # 策略引擎（因子计算、过滤、评分、排序）
│   ├── multi_factor.py    # 多因子轮动策略（动量+估值+低波等权）
│   ├── factor_analysis.py # 因子有效性检验（RankIC/ICIR/分层回测）
│   ├── scoring.py         # Z-score标准化 + 等权加权评分
│   ├── backtest_utils.py  # 回测公共工具函数
│   ├── optimizer.py       # 参数网格搜索 + 参数范围常量
│   ├── walk_forward.py    # Walk-Forward 优化引擎（5风格预设生成）
│   ├── factors/           # 因子库
│   │   ├── base.py       # 因子基类
│   │   ├── momentum.py   # 动量因子
│   │   ├── volatility.py # 波动率因子
│   │   ├── liquidity.py  # 流动性因子
│   │   └── valuation.py  # 估值百分位因子
│   └── filters/           # 过滤器库
│
├── data/                  # 数据层
│   ├── sources/           # 数据源
│   │   ├── base.py       # 数据源基类
│   │   ├── akshare_source.py  # akshare 数据源
│   │   └── hybrid_source.py   # 混合数据源（AkShare + Tushare）
│   └── storage/           # 数据存储
│       ├── db.py         # 数据库初始化和连接管理
│       ├── etf_repo.py   # ETF 基础信息仓库
│       ├── price_repo.py # 行情数据仓库
│       ├── valuation_repo.py # 估值数据仓库（含PE百分位计算）
│       ├── signal_repo.py # 策略信号仓库
│       └── portfolio_repo.py # 持仓跟踪仓库
│
├── scripts/               # 脚本
│   ├── verify_factors.py  # 因子验证脚本
│   └── optimize_presets.py # Walk-Forward 参数优化 CLI（结果写回 settings.py）
│
├── config/                # 配置层
│   └── settings.py       # 全局配置（ETF池、策略参数）
│
├── utils/                 # 工具层
├── tests/                # 测试层
├── docs/                 # 文档
└── requirements.txt      # 依赖清单
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 Streamlit 页面

```bash
STREAMLIT_SERVER_HEADLESS=true STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
  .venv/bin/streamlit run presentation/streamlit_app.py --server.port 8501
```

启动后访问 [http://localhost:8501](http://localhost:8501)。

> 如果 8501 端口被占用，改用 `--server.port 8502` 等其他端口。

**页面功能：**

| 页签 | 功能 |
|------|------|
| 推荐列表 | Z-score 标准化 + 等权加权评分，ETF 排名 |
| 因子说明 | 因子方向、标准化方法、加权方式说明 |
| 回测结果 | 多因子轮动策略绩效指标（动量+估值+低波） |
| 净值曲线 | Plotly 交互式净值走势图（策略 vs 沪深300基准） |
| 因子诊断 | RankIC/ICIR、滚动 IC、五组分层收益和实际权重历史 |

**使用流程：**

1. 侧边栏选择 ETF 标的（默认 33 只全池）
2. 设置日期范围
3. 选择参数预设（5 个 Walk-Forward 优化预设之一，或自定义）
4. 点「运行回测」查看绩效指标、净值曲线、交易明细
5. 在回测结果中查看唯一的「因子诊断面板」
6. 下载本次运行的 HTML、Markdown 和 JSON 报告；数据质量阻断时只生成阻断报告，不生成模拟订单

### 数据可信度与报告

- 回测前校验交易日、重复记录、OHLC 关系、非负值和数据源差异。
- 价格源差异超过 1% 或成交量差异超过 10% 时阻断运行。
- 行情同时保存原始 OHLC 和 `adj_factor` 生成的信号价格：因子计算使用复权收盘价，模拟成交、手续费和持仓估值使用原始价格。
- 报告自动归档到 `reports/YYYY-MM-DD/<run_id>/`，包含代码版本、数据快照、参数、交易事实和因子状态。
- `report-data.json` 是供 AI 阅读的结构化事实；AI 只能据此生成带触发条件和风险边界的条件化建议。

### 因子生命周期

- 每月监控 RankIC、ICIR、分层收益、成本后收益和组合边际贡献。
- 候选因子必须完成 12 个月 OOS 初筛、24 个月 OOS 确认、人工批准和 1–3 个月影子运行。
- 正式新增或替换只在季度窗口执行，所有版本支持回滚。

月度监控使用按因子分组的观测 JSON 生成替换候选和观察名单：

```bash
.venv/bin/python -m presentation.cli.factor_lifecycle monthly-monitor \
  --observations observations.json --as-of-date 2026-01-31 --output reports/factors/2026-01
```

候选因子仍需经过沙箱试运行、12/24 个月 OOS、人工审批和影子运行；完成后在季度窗口发布：

```bash
.venv/bin/python -m presentation.cli.factor_lifecycle quarterly-publish \
  --candidates factors/candidates.json --registry factors/registry.json \
  --candidate-id candidate-xxx --publish-date 2026-04-01
```

AI 生成因子可通过 `service.factor_sandbox.FactorSandbox` 在独立进程中执行。沙箱限制导入和文件访问，输入文件只读，带源码哈希和超时；沙箱不会写入正式因子注册表。

### 参数预设优化（CLI）

预设由 Walk-Forward 优化生成，UI 不提供优化入口。重新生成预设：

````bash
.venv/bin/python scripts/optimize_presets.py --start 2019-01-01 --end 2024-12-31
````

- 默认 144 参数组合 × 12 验证窗口，耗时约 1-3 分钟
- 生成 5 个差异化预设（激进高收益/最优风险调整/均衡稳健/最低回撤/低频交易）
- 自动写回 `config/settings.py`，原文件备份至 `.bak`
- 加 `--dry-run` 仅查看结果不写回
- 加 `--output report.json` 额外输出 JSON 报告

### 3. 因子验证

验证所有因子计算是否正确（行情因子 + PE百分位 + Z-score标准化）：

```bash
.venv/bin/python scripts/verify_factors.py
```

## 架构说明

### 四层分层

```
┌─────────────────────────────────────────────────────────┐
│  表现层 presentation/   Streamlit 页面                  │
│    推荐列表、因子说明、回测结果、净值曲线、因子诊断      │
├─────────────────────────────────────────────────────────┤
│  服务层 service/        业务逻辑编排                    │
│    StrategyService / PortfolioService / DataService    │
├─────────────────────────────────────────────────────────┤
│  策略层 strategy/       因子 → 标准化 → 评分 → 回测     │
│    动量/波动率/估值因子；Z-score等权加权                 │
│    多因子轮动策略（动量+估值+低波）+ Walk-Forward优化    │
├─────────────────────────────────────────────────────────┤
│  数据层 data/          AkShare+Tushare → SQLite → Repo  │
│    行情数据、5000+条PE历史、ETF→指数映射                │
└─────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级                | 职责                       | 依赖方向                   |
| ------------------- | -------------------------- | -------------------------- |
| presentation 表现层 | Streamlit 页面 + 交互      | 通过 service 获取数据和诊断 |
| service 服务层      | 业务逻辑编排、接口封装     | 依赖 strategy + data 层    |
| strategy 策略层     | 多因子评分/回测/WF优化引擎  | 只依赖 data 层（价格数据） |
| data 数据层         | 数据获取 + 存储            | 无上层依赖                 |

## 运行测试

```bash
python -m pytest tests/ -v
```

## 扩展方向

1. **AI 因子挖掘**
   - 使用深度学习自动挖掘有效因子
   - 基于 Transformer 的多因子融合模型

2. **智能选股优化**
   - 强化学习驱动的动态仓位管理
   - 多目标优化的选股策略

3. **行情预测**
   - LSTM/Transformer 时序预测模型
   - 多模态融合（价格+成交量+情绪）预测

4. **智能回测与风险控制**
   - AI 驱动的策略参数自动调优
   - 基于机器学习的风险预警系统

5. **自然语言处理**
   - 财经新闻情感分析辅助选股
   - 政策事件影响评估
