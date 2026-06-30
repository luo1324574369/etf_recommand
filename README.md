# ETF 量化推荐系统

一个基于 Python 的 ETF 量化选股和推荐系统，集成了数据获取、策略计算、回测分析和 Web 展示功能。

## 技术栈

- **Python 3.x** - 核心开发语言
- **SQLite** - 轻量级本地数据库，存储 ETF 基础信息和行情数据
- **Flask + Jinja2** - Web 框架和模板引擎，提供可视化界面
- **akshare** - 开源财经数据接口，用于获取 ETF 行情数据
- **pandas** - 数据处理和分析库

## 项目结构

```
etf_recommand/
├── backtest/                # 回测引擎层
│   ├── engine.py            # 回测核心引擎
│   └── metrics.py           # 回测指标计算
├── config/                  # 配置层
│   └── settings.py          # 全局配置（ETF池、策略参数、Web配置）
├── data/                    # 数据层
│   ├── sources/             # 数据源
│   │   ├── base.py          # 数据源基类
│   │   └── akshare_source.py # akshare 数据源实现
│   └── storage/             # 数据存储
│       ├── db.py            # 数据库初始化和连接管理
│       ├── etf_repo.py      # ETF 基础信息仓库
│       ├── price_repo.py    # 行情数据仓库
│       └── signal_repo.py   # 策略信号仓库
├── scripts/                 # 脚本层
│   ├── update_data.py       # 数据更新脚本
│   └── run_strategy.py      # 策略运行脚本
├── strategy/                # 策略层
│   ├── engine.py            # 策略引擎（因子计算、过滤、评分、排序）
│   ├── factors/             # 因子库
│   │   ├── base.py          # 因子基类
│   │   ├── momentum.py      # 动量因子
│   │   ├── trend.py         # 趋势因子
│   │   └── volume.py        # 成交量因子
│   └── filters/             # 过滤器库
│       ├── base.py          # 过滤器基类
│       ├── momentum_filter.py # 动量过滤器
│       ├── trend_filter.py  # 趋势过滤器
│       └── volume_filter.py # 成交量过滤器
├── tests/                   # 测试层
│   ├── test_etf_repo.py
│   ├── test_price_repo.py
│   ├── test_signal_repo.py
│   ├── test_strategy_engine.py
│   ├── test_strategy_factors.py
│   ├── test_strategy_filters.py
│   ├── test_utils_date.py
│   ├── test_web_templates.py
│   └── test_run_strategy.py
├── utils/                   # 工具层
│   └── date.py              # 日期工具函数
├── web/                     # Web 层
│   ├── app.py               # Flask 应用工厂
│   ├── routes/              # 路由
│   │   ├── home.py          # 首页路由
│   │   ├── etf.py           # ETF 详情路由
│   │   └── backtest.py      # 回测路由
│   ├── templates/           # 模板
│   │   ├── base.html        # 基础布局
│   │   ├── index.html       # 首页模板
│   │   ├── etf_detail.html  # ETF详情模板
│   │   └── backtest.html    # 回测页面模板
│   └── static/              # 静态资源
│       └── style.css        # 样式文件
├── requirements.txt         # 依赖清单
└── README.md                # 项目说明
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 更新数据

从 akshare 获取 ETF 基础信息和历史行情数据：

```bash
python scripts/update_data.py
```

可选参数：
- `--full` 全量更新（默认增量更新）
- `--code 510300,510500` 只更新指定 ETF 代码
- `--db /path/to/etf.db` 指定数据库路径

### 3. 运行策略

执行量化选股策略，生成推荐信号：

```bash
python scripts/run_strategy.py
```

可选参数：
- `--strategy momentum_weekly` 策略名称（默认: momentum_weekly）
- `--date 2025-01-01` 信号日期（默认今天）
- `--db /path/to/etf.db` 指定数据库路径

### 4. 启动 Web 服务

```bash
python -m web.app
```

启动后访问 [http://localhost:5000](http://localhost:5000) 查看推荐列表和 ETF 详情。

## 运行测试

执行所有单元测试：

```bash
python -m unittest discover tests -v
```

## 扩展路径（AI 相关模块）

以下是一些可扩展的 AI 相关方向：

1. **AI 因子挖掘**
   - 使用深度学习自动挖掘有效因子
   - 基于 Transformer 的多因子融合模型
   - 因子重要性分析和自动选择

2. **智能选股优化**
   - 强化学习驱动的动态仓位管理
   - 基于图神经网络的行业关联分析
   - 多目标优化的选股策略

3. **行情预测**
   - LSTM/Transformer 时序预测模型
   - 多模态融合（价格+成交量+情绪）预测
   - 概率分布预测和不确定性估计

4. **智能回测与风险控制**
   - AI 驱动的策略参数自动调优
   - 基于机器学习的风险预警系统
   - 蒙特卡洛模拟与极端场景测试

5. **自然语言处理**
   - 财经新闻情感分析辅助选股
   - 研报摘要自动提取和分析
   - 政策事件影响评估

6. **模型监控与迭代**
   - 策略表现自动监控和漂移检测
   - 在线学习与模型持续更新
   - A/B 测试框架与效果评估
