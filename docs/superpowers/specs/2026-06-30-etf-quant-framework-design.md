# ETF 量化推荐项目基础框架设计

> 日期：2026-06-30
> 状态：设计中

## 1. 项目概述

### 1.1 目标

搭建一个 ETF 量化推荐系统的基础框架，首期实现周频板块动量轮动策略的完整链路（数据获取 → 策略计算 → 结果展示），同时为后续 AI 模块（题材验证、情绪打分、因子增强、风控预警）预留清晰的扩展接口。

### 1.2 技术栈

- **语言**：Python 3
- **数据库**：SQLite（原生 SQL + sqlite3）
- **Web 框架**：Flask + Jinja2
- **行情数据源**：akshare（可插拔）
- **前端**：纯 HTML/CSS + 轻量图表（CDN 引入）

### 1.3 首期交付范围

| 模块 | 状态 | 说明 |
|------|------|------|
| 数据层 | ✅ 完整实现 | akshare 行情获取 + SQLite 存储 + 增量更新 |
| 策略层 | ✅ 完整实现 | 周频动量轮动：趋势过滤 + 动量排名 + 量能验证 + 综合得分 |
| 回测层 | ⚠️ 框架预留 | 接口和类结构定义，具体逻辑不实现 |
| Web 层 | ✅ 基础页面 | 首页推荐列表 + ETF 详情页 + 回测页占位 |
| AI 模块 | ❌ 不实现 | 架构预留扩展点，不写代码 |

## 2. 整体架构

### 2.1 分层架构

```
┌─────────────────────────────────────────────────┐
│                   Web 层 (Flask)                 │
│  routes  │  templates  │  static                │
├─────────────────────────────────────────────────┤
│                  策略层 (strategy)               │
│  factors  │  filters  │  engine  │  signals     │
├─────────────────────────────────────────────────┤
│                  回测层 (backtest)               │
│  engine  │  metrics  │  results                 │
├─────────────────────────────────────────────────┤
│                   数据层 (data)                  │
│  sources(akshare...)  │  storage(sqlite)        │
├─────────────────────────────────────────────────┤
│              配置层 & 工具层 (config/utils)       │
└─────────────────────────────────────────────────┘
```

### 2.2 设计原则

1. **单向依赖**：上层依赖下层，下层不感知上层。策略层不知道 Web 层存在，数据层不知道策略层存在。
2. **接口抽象**：数据源、因子、筛选规则都定义成基类/接口，实现可插拔。
3. **数据流转**：`数据源 → 数据库 → 因子计算 → 筛选 → 策略输出 → Web 展示`
4. **配置驱动**：策略参数通过配置文件管理，不硬编码在逻辑中。

### 2.3 目录结构

```
etf_recommand/
├── config/
│   ├── __init__.py
│   └── settings.py           # 全局配置（路径、策略参数、ETF池）
├── data/
│   ├── __init__.py
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py           # 数据源抽象基类
│   │   └── akshare_source.py # akshare 实现
│   └── storage/
│       ├── __init__.py
│       ├── db.py             # SQLite 连接管理 + 表初始化
│       ├── etf_repo.py       # ETF 基础信息表操作
│       ├── price_repo.py     # 行情数据表操作
│       └── signal_repo.py    # 策略信号/推荐结果表操作
├── strategy/
│   ├── __init__.py
│   ├── factors/
│   │   ├── __init__.py
│   │   ├── base.py           # 因子抽象基类
│   │   ├── momentum.py       # 动量因子（10日涨幅等）
│   │   ├── trend.py          # 趋势因子（20日均线等）
│   │   └── volume.py         # 量能因子（成交量放大等）
│   ├── filters/
│   │   ├── __init__.py
│   │   ├── base.py           # 筛选器抽象基类
│   │   ├── trend_filter.py   # 趋势过滤（站上20日均线）
│   │   ├── momentum_filter.py# 动量排名筛选
│   │   └── volume_filter.py  # 资金验证筛选
│   └── engine.py             # 策略引擎（编排因子计算+筛选+排名）
├── backtest/
│   ├── __init__.py
│   ├── engine.py             # 回测引擎（框架，首期不实现逻辑）
│   └── metrics.py            # 绩效指标计算（框架，首期不实现）
├── web/
│   ├── __init__.py
│   ├── app.py                # Flask 应用入口（工厂函数）
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── home.py           # 首页：当前推荐
│   │   ├── etf.py            # ETF 详情页
│   │   └── backtest.py       # 回测页
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── etf_detail.html
│   │   └── backtest.html
│   └── static/
│       └── style.css
├── utils/
│   ├── __init__.py
│   └── date.py               # 日期工具
├── scripts/
│   ├── update_data.py        # 数据更新脚本
│   └── run_strategy.py       # 跑策略生成推荐脚本
├── data/
│   └── etf.db                # SQLite 数据库文件（运行时生成）
├── requirements.txt
└── README.md
```

### 2.4 AI 模块扩展点

为未来 AI 模块预留以下扩展位置：

- **`strategy/factors/`**：新增 `ai_sentiment.py`（AI 情绪因子）、`ai_theme.py`（AI 题材热度因子）等
- **`strategy/filters/`**：新增 `ai_sentiment_filter.py`（AI 舆情过热筛除）
- **独立 `ai/` 顶层目录**：如 AI 模块较重（需要独立的数据采集、模型调用），可新建顶层 `ai/` 目录，数据从数据库读，结果写回数据库，策略层通过因子/筛选器接入

## 3. 数据层设计

### 3.1 数据库表

#### 表1：`etf_info` — ETF 基础信息

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| code | TEXT | PRIMARY KEY | ETF 代码（如 510300） |
| name | TEXT | NOT NULL | ETF 名称（如 沪深300ETF） |
| sector | TEXT | | 所属板块/行业 |
| type | TEXT | | 类型：行业/主题/宽基 |
| listed_date | TEXT | | 上市日期（YYYY-MM-DD） |
| is_active | INTEGER | DEFAULT 1 | 是否在标的池中（1=是，0=否） |

#### 表2：`etf_daily_price` — 日线行情数据

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| code | TEXT | NOT NULL | ETF 代码 |
| trade_date | TEXT | NOT NULL | 交易日（YYYY-MM-DD） |
| open | REAL | | 开盘价 |
| high | REAL | | 最高价 |
| low | REAL | | 最低价 |
| close | REAL | NOT NULL | 收盘价 |
| volume | INTEGER | | 成交量（手） |
| amount | REAL | | 成交额（元） |
| PRIMARY KEY | | (code, trade_date) | 联合主键 |

索引建议：`trade_date` 单列索引（用于范围查询）。

#### 表3：`strategy_signal` — 策略推荐信号

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增ID |
| signal_date | TEXT | NOT NULL | 信号生成日期 |
| strategy_name | TEXT | NOT NULL | 策略名称（如 momentum_weekly） |
| code | TEXT | NOT NULL | ETF 代码 |
| name | TEXT | | ETF 名称（冗余，方便查询） |
| rank | INTEGER | | 排名 |
| score | REAL | | 综合得分 |
| reason | TEXT | | 入选理由（JSON 格式，存各因子得分） |
| action | TEXT | | 操作建议：buy/hold/sell |
| created_at | TEXT | | 创建时间 |

索引建议：`(signal_date, strategy_name)` 联合索引。

### 3.2 数据源抽象

```python
# data/sources/base.py
class DataSourceBase:
    """数据源抽象基类，所有数据源实现必须继承此类"""

    def get_etf_list(self) -> list[dict]:
        """获取 ETF 列表
        返回: [{code, name, ...}, ...]
        """
        raise NotImplementedError

    def get_daily_price(self, code: str, start_date: str, end_date: str) -> list[dict]:
        """获取单只 ETF 日线数据
        返回: [{trade_date, open, high, low, close, volume, amount}, ...]
        """
        raise NotImplementedError

    def get_daily_price_batch(self, codes: list[str], start_date: str, end_date: str) -> dict[str, list[dict]]:
        """批量获取日线数据
        返回: {code: [price_data, ...], ...}
        """
        raise NotImplementedError
```

`akshare_source.py` 继承 `DataSourceBase`，用 akshare 实现上述方法。

### 3.3 数据存储层（Repository 模式）

每张表对应一个 repo 类，封装所有 SQL 操作。上层只调用 repo 方法，不直接写 SQL。

- `ETFRepository`：`etf_info` 表的增删改查
- `PriceRepository`：`etf_daily_price` 表的增删改查
- `SignalRepository`：`strategy_signal` 表的增删改查

每个 repo 接收数据库连接对象（`sqlite3.Connection`）作为构造参数。

### 3.4 数据库连接管理

`data/storage/db.py` 提供：

- `init_db(db_path)`：创建所有表（如果不存在）
- `get_db(db_path)`：获取数据库连接（设置 `row_factory = sqlite3.Row`，方便按字段名访问）
- 统一的连接关闭机制

### 3.5 数据更新流程

入口脚本：`scripts/update_data.py`

流程：
1. 读取配置中的 ETF 池列表
2. 对每只 ETF，查询数据库中的最新交易日
3. 如果有缺失日期，从 akshare 拉取增量数据
4. 写入数据库（INSERT OR IGNORE，幂等）
5. 打印更新统计

支持参数：
- `--full`：全量更新（忽略已有数据，重新拉取全部）
- `--code 510300`：只更新指定 ETF

## 4. 策略层设计

### 4.1 核心模式：Factor → Filter → Engine

- **Factor（因子）**：计算单个指标，输出数值或结构化结果
- **Filter（筛选器）**：基于因子值做筛选判断，输出 (是否通过, 得分)
- **Engine（引擎）**：编排因子计算 → 筛选 → 排序 → 输出推荐列表

### 4.2 因子层

```python
# strategy/factors/base.py
class FactorBase:
    """因子抽象基类"""
    name: str = ""
    description: str = ""

    def calculate(self, code: str, price_data: list[dict], end_date: str) -> float | dict:
        """
        计算因子值
        - price_data: 该 ETF 的日线数据列表（按日期升序）
        - end_date: 计算截止日期
        返回: 因子值（数值或 dict）
        """
        raise NotImplementedError
```

首期实现的因子：

| 因子 | 类名 | 文件 | 输出 | 说明 |
|------|------|------|------|------|
| 动量因子 | `MomentumFactor` | `momentum.py` | float | 近 N 日涨幅（默认 10 日） |
| 趋势因子 | `TrendFactor` | `trend.py` | dict | {ma20, above_ma20, price} |
| 量能因子 | `VolumeFactor` | `volume.py` | float | 近短周期均量 / 近长周期均量 |

### 4.3 筛选层

```python
# strategy/filters/base.py
class FilterBase:
    """筛选器抽象基类"""
    name: str = ""

    def apply(self, code: str, factor_values: dict) -> tuple[bool, float]:
        """
        应用筛选规则
        - factor_values: 所有因子的计算结果 {factor_name: value}
        返回: (是否通过筛选, 得分)
        """
        raise NotImplementedError
```

首期筛选器：

| 筛选器 | 类名 | 文件 | 规则 | 得分 |
|--------|------|------|------|------|
| 趋势过滤 | `TrendFilter` | `trend_filter.py` | 收盘价 > MA20 → 通过 | 通过=1，不通过=0（硬过滤，不通过直接剔除） |
| 动量筛选 | `MomentumFilter` | `momentum_filter.py` | 10日涨幅排名前 30% → 通过 | 涨幅值（用于排名） |
| 量能过滤 | `VolumeFilter` | `volume_filter.py` | 近5日均量/20日均量 > 1.2 → 通过 | 放大倍率（用于排名） |

**筛选器应用顺序：**
1. **硬过滤（TrendFilter）**：先应用，不通过的直接剔除，不进入后续计算
2. **排名筛选（MomentumFilter）**：在通过硬过滤的标的中，按动量涨幅取前 30%
3. **量能验证（VolumeFilter）**：剩余标的再检查量能条件，不通过的剔除
4. **综合打分排序**：通过所有筛选的标的，按加权综合得分排序，取前 N 名

**综合得分计算方式：**
- 各因子得分先做 min-max 归一化（0~1 区间），消除量纲差异
- 按 `score_weights` 配置的权重加权求和
- `score_weights` 的 key 与因子 name 对应

### 4.4 策略引擎

```python
# strategy/engine.py
class StrategyEngine:
    """策略引擎：编排因子计算与筛选流程"""

    def __init__(self, factors: list[FactorBase], filters: list[FilterBase],
                 top_n: int = 5, score_weights: dict = None):
        self.factors = factors
        self.filters = filters
        self.top_n = top_n
        self.score_weights = score_weights or {}

    def run(self, etf_codes: list[str], end_date: str, price_repo) -> list[dict]:
        """
        执行一次选股，返回推荐列表
        1. 批量拉取价格数据
        2. 逐只计算所有因子
        3. 逐只应用所有筛选器
        4. 综合得分排序，选前 N 名
        """
        ...
```

### 4.5 出场规则

出场规则作为策略引擎的方法 `check_exit(holdings, current_date, price_repo)`，输入当前持仓 + 最新数据，输出卖出信号列表。

首期实现完整的出场判定逻辑（因为策略层首期完整实现），包含以下规则（触发任一即卖出）：

- **跌破 20 日均线**：收盘价 < MA20 → 卖出
- **掉出前 N 名**：不在最新一期推荐列表中 → 卖出
- **硬性止损**：单只浮亏 ≥ 8% → 卖出

**持仓跟踪说明：** 首期不做完整的账户/持仓管理系统，持仓信息通过 `strategy_signal` 表的历史信号简单模拟（买入信号产生时记录成本价，后续调仓日对比）。完整的持仓与账户管理留待回测层完善时统一实现。

### 4.6 策略配置化

所有策略参数放在 `config/settings.py`，不硬编码：

```python
STRATEGY_CONFIG = {
    "momentum_weekly": {
        "name": "周频板块动量轮动",
        "rebalance_freq": "weekly",
        "top_n": 5,
        "factors": [
            {"class": "MomentumFactor", "params": {"period": 10}},
            {"class": "TrendFactor", "params": {"period": 20}},
            {"class": "VolumeFactor", "params": {"short_period": 5, "long_period": 20}},
        ],
        "filters": [
            {"class": "TrendFilter", "params": {}},
            {"class": "MomentumFilter", "params": {"top_pct": 0.3}},
            {"class": "VolumeFilter", "params": {"min_ratio": 1.2}},
        ],
        "score_weights": {
            "momentum": 0.5,
            "volume": 0.3,
        },
        "exit_rules": {
            "max_loss_pct": 0.08,
            "below_ma20": True,
            "drop_out_of_top_n": True,
        },
        "position": {
            "max_single_pct": 0.25,
            "max_total_pct": 0.8,
        },
    }
}
```

### 4.7 ETF 标的池

配置中维护 20~30 只主流行业/主题 ETF 列表，覆盖科技、消费、周期、金融、医药等大类。示例：

```python
ETF_UNIVERSE = [
    {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "宽基"},
    {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "宽基"},
    {"code": "512880", "name": "证券ETF", "sector": "金融", "type": "行业"},
    {"code": "512200", "name": "房地产ETF", "sector": "金融", "type": "行业"},
    {"code": "512690", "name": "酒ETF", "sector": "消费", "type": "行业"},
    # ... 更多
]
```

## 5. 回测层设计

### 5.1 定位

首期只搭框架，不实现具体回测逻辑。确保架构上有回测模块的位置，后续可以直接填充。

### 5.2 回测引擎

```python
# backtest/engine.py
class BacktestEngine:
    def __init__(self, strategy, price_repo, initial_capital: float = 1000000,
                 commission_rate: float = 0.0003):
        self.strategy = strategy          # StrategyEngine 实例
        self.price_repo = price_repo
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.positions = {}               # {code: {shares, cost_basis}}
        self.cash = initial_capital
        self.trade_history = []           # 交易记录
        self.daily_nav = []               # 每日净值

    def run(self, etf_codes: list[str], start_date: str, end_date: str) -> dict:
        """运行回测（首期框架，具体逻辑待实现）"""
        raise NotImplementedError("回测逻辑待实现")

    def _rebalance(self, trade_date: str, signals: list[dict]):
        """执行调仓（首期框架）"""
        ...

    def _calculate_nav(self, trade_date: str):
        """计算当日净值（首期框架）"""
        ...
```

### 5.3 绩效指标

```python
# backtest/metrics.py
class BacktestMetrics:
    @staticmethod
    def calculate(daily_nav: list[dict]) -> dict:
        """计算绩效指标（首期返回空结构）"""
        return {
            "total_return": None,       # 总收益率
            "annual_return": None,      # 年化收益率
            "max_drawdown": None,       # 最大回撤
            "sharpe_ratio": None,       # 夏普比率
            "win_rate": None,           # 胜率
            "trade_count": None,        # 交易次数
            "profit_factor": None,      # 盈亏比
        }
```

## 6. Web 层设计

### 6.1 Flask 应用结构

采用**应用工厂**模式创建 Flask 应用：

```python
# web/app.py
def create_app(db_path: str = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or default_db_path
    # 注册蓝图
    from .routes.home import bp as home_bp
    from .routes.etf import bp as etf_bp
    from .routes.backtest import bp as backtest_bp
    app.register_blueprint(home_bp)
    app.register_blueprint(etf_bp)
    app.register_blueprint(backtest_bp)
    return app
```

### 6.2 路由设计

| 路由 | 模块 | 页面 | 说明 |
|------|------|------|------|
| `/` | `routes/home.py` | 首页 | 展示最新一期策略推荐列表 |
| `/etf/<code>` | `routes/etf.py` | ETF 详情页 | 单只 ETF 的基本信息、价格走势、因子值 |
| `/backtest` | `routes/backtest.py` | 回测页 | 回测入口和结果展示（首期占位） |

### 6.3 模板设计

- `base.html`：基础布局（导航栏 + 内容区 + 页脚）
- `index.html`：推荐列表表格（排名、代码、名称、得分、操作建议、入选理由）
- `etf_detail.html`：ETF 详情（基本信息 + 近期K线表格 + 因子指标）
- `backtest.html`：回测页占位（提示"功能开发中"）

### 6.4 前端技术

- 纯 Jinja2 模板渲染，不做前后端分离
- CSS 用原生 + 简单样式
- 图表：CDN 引入 echarts（如需要），首期可用 HTML 表格代替

## 7. 配置层 & 工具层

### 7.1 配置（config/settings.py）

包含：
- 数据库路径
- ETF 标的池列表
- 策略配置（见 4.6 节）
- 数据源配置（默认 akshare）
- Web 服务配置（端口、debug 模式等）

### 7.2 工具（utils/date.py）

常用日期工具函数：
- `is_trade_day(date)`：判断是否为交易日（简单版：排除周末）
- `prev_trade_day(date)`：前一个交易日
- `next_trade_day(date)`：后一个交易日
- `get_weekly_rebalance_date(date)`：找到给定日期所在周的周五
- `shift_trade_days(date, n)`：偏移 N 个交易日

## 8. 脚本入口

### 8.1 `scripts/update_data.py`

更新行情数据到最新交易日。

用法：
```bash
python scripts/update_data.py            # 增量更新所有ETF
python scripts/update_data.py --full     # 全量更新
python scripts/update_data.py --code 510300  # 只更新指定ETF
```

### 8.2 `scripts/run_strategy.py`

运行策略，生成最新推荐信号，写入数据库。

用法：
```bash
python scripts/run_strategy.py                     # 默认策略（周频动量）
python scripts/run_strategy.py --strategy xxx      # 指定策略
python scripts/run_strategy.py --date 2026-06-27   # 指定计算日期
```

### 8.3 典型使用流程

```
1. python scripts/update_data.py    # 拉取最新行情
2. python scripts/run_strategy.py   # 生成推荐信号
3. 启动 Flask，打开浏览器查看结果
```

## 9. 依赖清单（requirements.txt 草案）

```
flask>=2.0
akshare>=1.0
```

注：akshare 可能依赖 pandas、numpy 等，会被自动安装。

## 10. 未来扩展路径

### 10.1 AI 题材逻辑验证
- 新增 `ai/news_collector.py`：采集财联社、研报等新闻
- 新增 `ai/theme_analyzer.py`：调用大模型分析题材
- 新增 `strategy/factors/ai_theme.py`：AI 题材热度因子
- 新增 `strategy/filters/ai_theme_filter.py`：AI 题材筛选

### 10.2 AI 舆情情绪打分
- 新增 `ai/sentiment.py`：舆情采集 + 情绪打分
- 新增 `strategy/factors/ai_sentiment.py`：情绪因子
- 策略中加入情绪分作为权重调整因素

### 10.3 AI 因子增强（XGBoost 等）
- 新增 `ai/ml_factor.py`：机器学习模型训练与预测
- 模型输出直接作为排序依据，或作为额外因子加入现有策略

### 10.4 AI 风控预警
- 新增 `ai/risk_monitor.py`：实时监控利空消息
- 通过消息通知（待接入）触发预警

## 11. 不在首期范围内的内容

- AI 相关的任何具体实现
- 回测引擎的具体逻辑（仅框架）
- 用户系统、登录注册
- 实盘交易接口
- 移动端适配
- 复杂的可视化图表
