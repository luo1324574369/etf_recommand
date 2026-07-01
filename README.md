# ETF 量化推荐系统

一个基于 Python 的 ETF 量化选股系统，采用经典五层分层架构，支持命令行终端（优先）和 Web 两种展示方式。

## 技术栈

- **Python 3.x** - 核心开发语言
- **SQLite** - 轻量级本地数据库，存储 ETF 基础信息和行情数据
- **akshare** - 开源财经数据接口，用于获取 ETF 行情数据
- **pandas** - 数据处理和分析库
- **Flask + Jinja2**（可选）- Web 界面，通过 `python -m presentation.app` 启动

## 项目结构（五层分层架构）

```
etf_recommand/
├── presentation/            # 表现层（展示 + 交互）
│   ├── cli/                # 命令行展示模块
│   │   ├── render.py      # 渲染工具（颜色、表格、分隔线）
│   │   ├── signal.py      # 策略信号展示
│   │   ├── etf.py         # ETF 详情展示
│   │   ├── portfolio.py   # 持仓展示
│   │   └── terminal.py    # 交互式终端菜单（入口：python scripts/terminal.py）
│   ├── routes/             # Web 路由（可选功能）
│   │   ├── home.py        # 首页信号
│   │   ├── etf.py         # ETF 详情
│   │   ├── portfolio.py   # 持仓管理
│   │   ├── cmd.py         # 一键操作接口
│   │   └── backtest.py    # 回测页
│   ├── templates/          # HTML 模板
│   ├── static/             # 静态资源
│   └── app.py             # Flask 应用工厂
│
├── service/                # 服务层（业务逻辑编排）
│   ├── strategy_service.py # 策略运行、信号查询
│   ├── portfolio_service.py # 账户、买卖、持仓盈亏计算
│   └── data_service.py    # ETF 详情、价格、因子计算
│
├── strategy/               # 策略层
│   ├── engine.py          # 策略引擎（因子计算、过滤、评分、排序）
│   ├── factors/           # 因子库
│   │   ├── base.py       # 因子基类
│   │   ├── momentum.py   # 动量因子
│   │   ├── trend.py      # 趋势因子
│   │   └── volume.py     # 成交量因子
│   └── filters/           # 过滤器库
│       ├── base.py        # 过滤器基类
│       ├── momentum_filter.py
│       ├── trend_filter.py
│       └── volume_filter.py
│
├── backtest/              # 回测层（框架预留）
│   ├── engine.py          # 回测核心引擎
│   └── metrics.py         # 回测指标计算
│
├── data/                  # 数据层
│   ├── sources/           # 数据源
│   │   ├── base.py       # 数据源基类
│   │   └── akshare_source.py  # akshare 数据源
│   └── storage/           # 数据存储
│       ├── db.py         # 数据库初始化和连接管理
│       ├── etf_repo.py   # ETF 基础信息仓库
│       ├── price_repo.py # 行情数据仓库
│       ├── signal_repo.py # 策略信号仓库
│       └── portfolio_repo.py # 持仓跟踪仓库
│
├── config/                # 配置层
│   └── settings.py       # 全局配置（ETF池、策略参数）
│
├── scripts/               # 脚本层（入口脚本）
│   ├── terminal.py        # 交互式终端菜单（主入口）
│   ├── update_data.py     # 数据更新脚本
│   ├── run_strategy.py    # 策略运行脚本
│   ├── generate_strategy_doc.py  # 策略说明文档生成器
│   ├── init_account.py    # 账户初始化
│   ├── add_trade.py       # 交易录入（交互式）
│   └── show_portfolio.py  # 持仓展示
│
├── tests/                # 测试层
├── utils/                # 工具层
├── docs/                 # 文档
│   └── strategy_doc.md   # 自动生成的大白话策略说明
└── requirements.txt      # 依赖清单
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 交互式终端模式（推荐）

一键启动终端菜单，所有操作通过数字选择完成：

```bash
python scripts/terminal.py
```

菜单选项：
- `[1]` 运行策略
- `[2]` 更新行情数据
- `[3]` 全量更新数据
- `[4]` 生成策略说明
- `[5]` 查看持仓
- `[6]` 录入交易
- `[7]` 初始化账户
- `[q]` 退出

### 3. 更新数据

从 akshare 拉取 ETF 历史行情数据：

```bash
python scripts/update_data.py
```

可选参数：
- `--full` 全量更新（从 2018 年开始，默认增量更新）
- `--code 510300,510500` 只更新指定 ETF
- `--db /path/to/etf.db` 指定数据库路径

### 4. 运行策略（命令行展示）

```bash
python scripts/run_strategy.py
```

可选参数：
- `--strategy momentum_weekly` 策略名称（默认: momentum_weekly）
- `--date 2026-01-01` 信号日期（默认今天）
- `--db /path/to/etf.db` 指定数据库路径

运行后自动在终端输出带颜色和表格的信号报告。

### 5. 启动 Web 界面（可选）

```bash
python -m presentation.app
```

启动后访问 [http://localhost:5002](http://localhost:5002)，提供一键操作面板。

### 6. 持仓跟踪（可选）

记录你的买卖情况：

```bash
# 初始化账户
python scripts/init_account.py

# 录入交易（交互式）
python scripts/add_trade.py

# 查看持仓
python scripts/show_portfolio.py
```

## 架构说明

### 五层分层

```
┌─────────────────────────────────────────────────────────┐
│  表现层 presentation/   CLI 终端（优先）+ Web（可选）   │
│    输出信号、ETF详情、持仓、交互式终端菜单              │
├─────────────────────────────────────────────────────────┤
│  服务层 service/        业务逻辑编排                    │
│    StrategyService / PortfolioService / DataService    │
├─────────────────────────────────────────────────────────┤
│  策略层 strategy/       因子 → 筛选 → 评分 → 排序      │
│    动量因子、趋势因子、量能因子；三重过滤器              │
├─────────────────────────────────────────────────────────┤
│  回测层 backtest/      框架预留（暂不实现）            │
│    历史回测引擎、绩效指标、收益曲线可视化                │
├─────────────────────────────────────────────────────────┤
│  数据层 data/          akshare → SQLite → Repository   │
│    财经数据源、增量更新、六张核心表                      │
└─────────────────────────────────────────────────────────┘
```

### 各层职责

| 层级 | 职责 | 依赖方向 |
|------|------|----------|
| presentation 表现层 | 展示 + 用户交互（CLI/Web） | 只依赖 service 层 |
| service 服务层 | 业务逻辑编排、接口封装 | 依赖 strategy + data 层 |
| strategy 策略层 | 因子/过滤/选股引擎 | 只依赖 data 层（价格数据） |
| backtest 回测层 | 历史回测（预留） | 依赖 strategy + data 层 |
| data 数据层 | 数据获取 + 存储 | 无上层依赖 |

### 策略说明

运行 `python scripts/run_strategy.py` 后会自动更新 `docs/strategy_doc.md`，用大白话说明当前策略逻辑。

## 运行测试

```bash
python -m pytest tests/ -v
```

## 扩展路径（AI 相关模块）

以下是一些可扩展的 AI 相关方向：

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
