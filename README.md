# ETF 量化推荐系统

一个基于 Python 的 ETF 量化选股系统，Streamlit 交互式页面，支持多因子评分、策略回测和净值曲线展示。

## 当前实现状态

- 正式回测入口为 `service.ApplicationService` → `strategy.multi_factor`，保证面板、CLI 和报告使用同一套策略口径。
- 系统只生成 HTML、Markdown、JSON 和运行清单等静态事实报告，不调用或部署 AI，也不提供系统定时调度。
- 回测执行前必须通过行情数据质量门禁；阻断时归档阻断报告，不生成模拟订单。
- 因子失效只生成健康状态和替换候选，不自动改写正式因子；候选必须经过 OOS、人工审批、影子运行和季度发布。

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
│   ├── application_service.py # 正式回测编排、数据门禁、报告归档
│   ├── strategy_service.py # 旧信号策略兼容层
│   ├── portfolio_service.py # 账户、买卖、持仓盈亏计算
│   └── data_service.py    # ETF 详情、价格、因子计算、数据更新
│
├── strategy/               # 策略层
│   ├── multi_factor.py    # 正式多因子轮动策略
│   ├── engine.py          # 旧信号策略兼容引擎（legacy）
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
│   ├── contracts.py       # 行情快照、质量报告和校验问题契约
│   ├── quality.py         # 行情结构、可交易性和跨源质量校验
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
│   ├── optimize_presets.py # Walk-Forward 参数优化 CLI
│   ├── build_autopilot_candidates.py # 生成自主优化候选事实
│   └── run_autopilot.py    # 自主评分、发布、回滚和报告 CLI
│
├── config/                # 配置层
│   ├── settings.py       # 默认值和代码常量
│   ├── versioned_strategy.py # 当前激活版本读取
│   └── strategy_versions/ # 版本化策略配置和回滚记录
│
├── utils/                 # 工具层
├── tests/                # 测试层
├── docs/                 # ADR、设计和运行文档
├── reports/              # 回测静态报告归档（运行时生成）
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
| 数据质量 | 快照来源、覆盖范围、复权状态、缺失日期和阻断原因 |
| 因子治理 | 因子健康、候选状态、OOS、影子运行和回滚状态 |

**使用流程：**

1. 侧边栏选择 ETF 标的（默认 33 只全池）
2. 设置日期范围
3. 选择参数预设（5 个 Walk-Forward 优化预设之一，或自定义）
4. 点「运行回测」查看绩效指标、净值曲线、交易明细
5. 在回测结果中查看唯一的「因子诊断面板」
6. 下载本次运行的 HTML、Markdown 和 JSON 报告；数据质量阻断时只生成阻断报告，不生成模拟订单

### 数据可信度与报告

- 回测前创建行情快照，记录来源、数据版本、请求区间、实际覆盖日期、记录数、缺失日期、重复记录和内容哈希。
- 校验交易日、重复记录、OHLC 关系、非负值、成交量、异常价格跳变、停牌/无成交和结束日之后的次日开盘价。
- 价格源差异超过 1% 或成交量差异超过 10% 时阻断运行。
- 行情同时保存原始 OHLC 和复权信号价格：因子计算使用可信复权价格，模拟成交、手续费和持仓估值使用原始价格。缺失或非法 `adj_factor` 会标记为不可用，不再静默当作有效复权。
- Tushare 配置下优先读取 `fund_adj` 复权因子；无法提供可信复权因子时，正式回测会被阻断。
- 报告自动归档到 `reports/YYYY-MM-DD/<run_id>/`，包含 `run-manifest.json`、`report-data.json`、`report.md` 和 `report.html`。
- `report-data.json` 记录评估阶段、数据范围、参数哈希、代码版本、数据质量、交易事实、历史运行和因子治理状态。
- `report-data.json` 是供 AI 阅读的结构化事实；AI 只能据此生成带触发条件和风险边界的条件化建议。

报告状态分为：

- `passed`：数据质量通过，可以生成模拟回测事实。
- `blocked`：数据质量未通过，只归档问题和证据，禁止据此生成交易建议。

### 正式运行口径

```text
Streamlit / CLI
        │
        ▼
ApplicationService
        │  获取行情 → 创建快照 → 执行数据质量门禁
        │
        ├── blocked ──> 归档阻断报告并停止
        │
        ▼
strategy.multi_factor
        │  复权价格计算信号，原始价格模拟成交
        ▼
ReportArtifact
        └── HTML / Markdown / JSON / Manifest
```

`strategy.engine` 和 `service.strategy_service` 只保留历史信号链路兼容能力；新功能不得接入该链路。

### 因子生命周期

- 每月监控 12/24 个月 RankIC、ICIR、分层收益、衰减、市场阶段稳定性、风格暴露、成本后收益和组合边际贡献。
- 候选因子必须保存完整 OOS 区间和指标，完成 12 个月 OOS 初筛、24 个月 OOS 确认、相关性/边际贡献/行业暴露/风格暴露检查。
- 人工批准后进行 1–3 个月影子运行；影子完成必须绑定通过质量门禁的正式回测报告，不能只提交手工收益数字。
- 正式新增或替换只在季度窗口执行，保留旧版本、配置和报告，并提供 CLI 与面板回滚入口。

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

系统不部署或调用 AI。每次回测生成的 `report-data.json` 是静态事实报告，可由用户自行交给外部 AI 分析；系统只负责提供数据质量、历史对比、因子健康和治理状态，不自动生成交易建议。

因子治理的人工操作命令：

```bash
.venv/bin/python -m presentation.cli.factor_lifecycle record-oos \
  --candidates factors/candidates.json --registry factors/registry.json \
  --candidate-id candidate-xxx --months 12 --passed \
  --evidence oos-12m.json
.venv/bin/python -m presentation.cli.factor_lifecycle approve \
  --candidates factors/candidates.json --registry factors/registry.json \
  --candidate-id candidate-xxx --approver user
```

OOS 证据 JSON 至少包含 `start_date`、`end_date` 和 `metrics`。影子运行完成时，指标 JSON 必须引用通过质量门禁的正式回测报告：

```json
{
  "source": "formal_backtest",
  "run_id": "run-xxx",
  "status": "passed",
  "data_range": {"start_date": "2025-01-01", "end_date": "2025-03-31"},
  "total_return": 0.12
}
```

回滚示例：

```bash
.venv/bin/python -m presentation.cli.factor_lifecycle rollback \
  --candidates factors/candidates.json --registry factors/registry.json \
  --factor-name value --target-version 1.0.0 \
  --operator user --reason "影子运行回撤超过阈值"
```

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

### Codex 自主优化

项目提供 `$etf-autopilot` Skill，不接入外部 AI、不部署模型、不连接券商。Skill 读取正式运行报告，调用质量门禁和 Walk-Forward，生成参数/因子候选，执行 12/24 个月 OOS、最终留出集和压力测试，并根据风险调整后收益评分自动发布或回滚模拟策略。

先生成候选事实 JSON：

```bash
.venv/bin/python scripts/build_autopilot_candidates.py \
  --start 2019-01-01 --end 2026-05-01 \
  --output reports/autopilot/candidates.json \
  --max-combinations 20
```

随后调用 `$etf-autopilot` 完成候选读取、评分、版本发布和静态决策报告。正式版本保存在 `config/strategy_versions/`，发布分支使用 `codex/autopilot/<date>-<run-id>`，无候选通过时保持当前版本。

发现正式版本出现数据阻断、未来函数、代码异常或硬回撤突破时，可将正式运行指标交给同一入口执行立即回滚；连续三个评估窗口低于基线时也会回滚：

```bash
.venv/bin/python scripts/run_autopilot.py \
  --candidates reports/autopilot/<run-id>/candidates.json \
  --rollback-metrics reports/<date>/<run-id>/report-data.json \
  --version-root config/strategy_versions \
  --report-root reports/autopilot
```

### 3. 因子验证

验证所有因子计算是否正确（行情因子 + PE百分位 + Z-score标准化）：

```bash
.venv/bin/python scripts/verify_factors.py
```

## 架构说明

### 四层分层

```
┌─────────────────────────────────────────────────────────┐
│  表现层 presentation/   Streamlit / CLI                  │
│    页面展示、报告下载、月度监控、候选审批和回滚          │
├─────────────────────────────────────────────────────────┤
│  服务层 service/        业务编排与治理                  │
│    ApplicationService / ReportArtifact / Governance     │
├─────────────────────────────────────────────────────────┤
│  策略层 strategy/       因子 → 标准化 → 评分 → 回测      │
│    multi_factor 正式运行时；factor_lifecycle 因子治理   │
├─────────────────────────────────────────────────────────┤
│  数据层 data/           数据源 → 快照/门禁 → SQLite      │
│    AkShare/Tushare、复权状态、质量报告和仓库             │
└─────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级                | 职责                       | 依赖方向                   |
| ------------------- | -------------------------- | -------------------------- |
| presentation 表现层 | 页面、报告下载和治理操作 | 只通过 service 获取数据和执行动作 |
| service 服务层      | 数据门禁、正式回测、报告、治理状态机 | 依赖 strategy + data 层 |
| strategy 策略层     | 因子计算、评分、回测和生命周期指标 | 正式入口为 `multi_factor` |
| data 数据层         | 数据获取、快照、质量校验和持久化 | 不依赖上层业务 |

### 治理状态机

```text
submitted → screened → confirmed → approved
                                      │
                                      ▼
                                   shadow
                                      │
                                      ▼
                                publishable
                                      │
                                      ▼
                                    active
                                      │
                                      ▼
                                 rolled_back
```

状态转换均由人工显式触发，系统不会自动替换正式因子，也没有后台定时调度任务。

## 运行测试

```bash
.venv/bin/pytest -q
```

当前基线验证结果：`257 passed`，Streamlit 启动检查返回 `HTTP 200`。

## 后续扩展边界

1. **数据质量增强**：接入更完整的 A 股交易日历、复权因子源和停牌/涨跌停状态。
2. **报告增强**：增加基准归因、风险分解、报告版本保留和静态可视化附件。
3. **因子治理增强**：完善正式 OOS 运行器、影子净值曲线和行业/风格暴露计算。
4. **外部分析协作**：继续只输出结构化静态事实，由用户自行选择外部 AI 或人工分析；不在本系统内调用或部署 AI。
