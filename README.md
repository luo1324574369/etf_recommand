# ETF 量化推荐系统

一个基于 Python 的 ETF 量化选股系统，Streamlit 交互式页面，支持多因子评分、策略回测和净值曲线展示。

## 技术栈

- **Python 3.11+** - 核心开发语言
- **SQLite** - 轻量级本地数据库，存储 ETF 基础信息、行情和估值数据
- **AkShare** - 开源财经数据接口，获取 ETF 行情和指数 PE 历史数据
- **Tushare Pro** - 付费金融数据接口，获取个股估值数据（PE/PB/PS）
- **Backtrader** - 量化回测框架，支持策略历史回测和绩效分析
- **Streamlit** - 交互式数据可视化页面
- **Plotly** - 净值曲线等图表绘制
- **pandas** - 数据处理和分析库

## 项目结构（五层分层架构）

```
etf_recommand/
├── presentation/            # 表现层（Streamlit 页面）
│   └── streamlit_app.py   # Streamlit 量化策略页面（推荐列表/回测/净值曲线）
│
├── service/                # 服务层（业务逻辑编排）
│   ├── strategy_service.py # 策略运行、信号查询
│   ├── portfolio_service.py # 账户、买卖、持仓盈亏计算
│   └── data_service.py    # ETF 详情、价格、因子计算、数据更新
│
├── strategy/               # 策略层
│   ├── engine.py          # 策略引擎（因子计算、过滤、评分、排序）
│   ├── dual_momentum.py   # 双动量ETF轮动策略（含回测函数）
│   ├── valuation_dca.py   # 估值百分位定投策略（含回测函数）
│   ├── scoring.py         # Z-score标准化 + 等权加权评分
│   ├── backtest_utils.py  # 回测公共工具函数
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
│   └── verify_factors.py  # 因子验证脚本
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
| 回测结果 | 双动量轮动 / 估值定投策略绩效指标 |
| 净值曲线 | Plotly 交互式净值走势图 |

**使用流程：**

1. 侧边栏点「拉取ETF列表」→ 选择 ETF 标的
2. 设置日期范围 → 点「拉取行情数据」
3. 点「拉取PE历史数据」（获取 5000+ 条指数 PE 历史）
4. 在「推荐列表」页签点「生成推荐」
5. 在「回测结果」页签选择策略并点「运行回测」
6. 在「净值曲线」页签点「生成曲线」

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
│    推荐列表、因子说明、回测结果、净值曲线                │
├─────────────────────────────────────────────────────────┤
│  服务层 service/        业务逻辑编排                    │
│    StrategyService / PortfolioService / DataService    │
├─────────────────────────────────────────────────────────┤
│  策略层 strategy/       因子 → 标准化 → 评分 → 回测     │
│    动量/波动率/流动性/估值因子；Z-score等权加权          │
│    双动量轮动 + 估值定投策略（含Backtrader回测）         │
├─────────────────────────────────────────────────────────┤
│  数据层 data/          AkShare+Tushare → SQLite → Repo  │
│    行情数据、5000+条PE历史、ETF→指数映射                │
└─────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级                | 职责                       | 依赖方向                   |
| ------------------- | -------------------------- | -------------------------- |
| presentation 表现层 | Streamlit 页面 + 交互      | 只依赖 service / strategy 层 |
| service 服务层      | 业务逻辑编排、接口封装     | 依赖 strategy + data 层    |
| strategy 策略层     | 因子/评分/回测引擎          | 只依赖 data 层（价格数据） |
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
