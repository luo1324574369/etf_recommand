import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data" / "etf.db"

ETF_UNIVERSE = [
    # 宽基指数
    {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "指数"},
    {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "指数"},
    {"code": "159915", "name": "创业板ETF", "sector": "宽基", "type": "指数"},
    {"code": "588000", "name": "科创50ETF", "sector": "宽基", "type": "指数"},
    {"code": "510050", "name": "上证50ETF", "sector": "宽基", "type": "指数"},
    {"code": "159919", "name": "沪深300ETF", "sector": "宽基", "type": "指数"},
    # 消费
    {"code": "159928", "name": "消费ETF", "sector": "消费", "type": "行业"},
    {"code": "512690", "name": "酒ETF", "sector": "消费", "type": "行业"},
    {"code": "159996", "name": "家电ETF", "sector": "消费", "type": "行业"},
    # 医药
    {"code": "159992", "name": "创新药ETF", "sector": "医药", "type": "行业"},
    {"code": "512010", "name": "医药ETF", "sector": "医药", "type": "行业"},
    # 新能源
    {"code": "515030", "name": "新能源车ETF", "sector": "新能源", "type": "行业"},
    {"code": "515790", "name": "光伏ETF", "sector": "新能源", "type": "行业"},
    # 科技
    {"code": "159995", "name": "芯片ETF", "sector": "科技", "type": "行业"},
    {"code": "515000", "name": "科技ETF", "sector": "科技", "type": "行业"},
    {"code": "512480", "name": "半导体ETF", "sector": "科技", "type": "行业"},
    # 金融
    {"code": "512880", "name": "证券ETF", "sector": "金融", "type": "行业"},
    {"code": "512000", "name": "券商ETF", "sector": "金融", "type": "行业"},
    {"code": "512800", "name": "银行ETF", "sector": "金融", "type": "行业"},
    # 周期
    {"code": "159825", "name": "农业ETF", "sector": "周期", "type": "行业"},
    {"code": "515210", "name": "钢铁ETF", "sector": "周期", "type": "行业"},
    {"code": "515220", "name": "煤炭ETF", "sector": "周期", "type": "行业"},
    {"code": "512400", "name": "有色金属ETF", "sector": "周期", "type": "行业"},
    {"code": "512200", "name": "房地产ETF", "sector": "周期", "type": "行业"},
    # 商品
    {"code": "159985", "name": "豆粕ETF", "sector": "商品", "type": "商品"},
    {"code": "518880", "name": "黄金ETF", "sector": "商品", "type": "商品"},
    # 红利
    {"code": "510880", "name": "红利ETF", "sector": "红利", "type": "指数"},
    {"code": "512890", "name": "红利低波ETF", "sector": "红利", "type": "指数"},
    # 军工
    {"code": "512660", "name": "军工ETF", "sector": "军工", "type": "行业"},
    # 传媒
    {"code": "159805", "name": "传媒ETF", "sector": "传媒", "type": "行业"},
    {"code": "512980", "name": "传媒ETF", "sector": "传媒", "type": "行业"},
    # 海外
    {"code": "159920", "name": "恒生ETF", "sector": "海外", "type": "指数"},
    {"code": "513100", "name": "纳指ETF", "sector": "海外", "type": "指数"},
]

STRATEGY_CONFIG = {
    "momentum_weekly": {
        "name": "周频板块动量轮动",
        "rebalance_freq": "weekly",
        "top_n": 5,
        "factors": [
            {"class": "MomentumFactor", "period": 10},
            {"class": "TrendFactor", "period": 20},
            {"class": "VolumeFactor", "short_period": 5, "long_period": 20},
        ],
        "filters": [
            {"class": "TrendFilter", "enabled": True},
            {"class": "MomentumFilter", "top_pct": 0.4, "enabled": True},
            {"class": "VolumeFilter", "min_ratio": 1.1, "enabled": True},
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
    },
    "momentum_monthly": {
        "name": "月频动量趋势轮动",
        "rebalance_freq": "monthly",
        "top_n": 3,
        "factors": [
            {"class": "MomentumFactor", "period": 20, "name": "momentum_short"},
            {"class": "MomentumFactor", "period": 60, "name": "momentum_long"},
            {"class": "TrendFactor", "period": 40},
            {"class": "VolumeFactor", "short_period": 15, "long_period": 40},
            {"class": "LiquidityFactor", "period": 20},
        ],
        "filters": [
            {"class": "TrendFilter", "require_rising": True, "enabled": True},
            {"class": "MomentumFilter", "top_pct": 0.4, "factor_name": "momentum_long", "enabled": True},
            {"class": "VolumeFilter", "min_ratio": 0.8, "enabled": False},
            {"class": "LiquidityFilter", "min_avg_amount": 30000000, "enabled": True},
        ],
        "score_weights": {
            "momentum_short": 0.3,
            "momentum_long": 0.4,
            "volume": 0.3,
        },
        "exit_rules": {
            "max_loss_pct": 0.08,
            "below_ma20": True,
            "ma_period": 40,
            "take_profit_pct": 0.40,
            "drop_out_of_top_n": True,
            "ma_break_days": 3,
        },
        "market_timing": {
            "enabled": True,
            "benchmark": "510300",
            "period": 100,
            "sector_breadth": {
                "enabled": True,
                "min_ratio": 0.4,
                "ma_period": 40,
            },
        },
        "position": {
            "max_single_pct": 0.35,
            "max_total_pct": 0.9,
        },
    },
    "sector_rotation": {
        "name": "行业轮动策略",
        "rebalance_freq": "monthly",
        "top_n": 4,
        "factors": [
            {"class": "MomentumFactor", "period": 40},
            {"class": "TrendFactor", "period": 60},
            {"class": "VolumeFactor", "short_period": 10, "long_period": 30},
        ],
        "filters": [
            {"class": "TrendFilter", "enabled": True},
            {"class": "MomentumFilter", "top_pct": 0.5, "enabled": True},
            {"class": "SectorRotationFilter", "top_per_sector": 1, "enabled": True},
            {"class": "VolumeFilter", "min_ratio": 0.8, "enabled": False},
        ],
        "score_weights": {
            "momentum": 0.8,
            "volume": 0.1,
        },
        "exit_rules": {
            "max_loss_pct": 0.08,
            "below_ma20": True,
            "ma_period": 60,
            "take_profit_pct": 0.30,
            "drop_out_of_top_n": True,
        },
        "market_timing": {
            "enabled": True,
            "benchmark": "510300",
            "period": 120,
        },
        "position": {
            "max_single_pct": 0.30,
            "max_total_pct": 0.9,
        },
    },
    "momentum_reversion": {
        "name": "动量均值回归混合策略",
        "rebalance_freq": "monthly",
        "top_n": 3,
        "factors": [
            {"class": "MomentumFactor", "period": 60},
            {"class": "MeanReversionFactor", "period": 20},
            {"class": "TrendFactor", "period": 120},
            {"class": "VolumeFactor", "short_period": 20, "long_period": 60},
        ],
        "filters": [
            {"class": "TrendFilter", "enabled": True},
            {"class": "MomentumFilter", "top_pct": 0.4, "enabled": True},
            {"class": "SectorRotationFilter", "top_per_sector": 1, "enabled": True},
            {"class": "VolumeFilter", "min_ratio": 0.8, "enabled": False},
        ],
        "score_weights": {
            "momentum": 0.5,
            "mean_reversion": 0.3,
            "volume": 0.05,
        },
        "exit_rules": {
            "max_loss_pct": 0.05,
            "below_ma20": True,
            "ma_period": 60,
            "take_profit_pct": 0.35,
            "drop_out_of_top_n": True,
        },
        "market_timing": {
            "enabled": True,
            "benchmark": "510300",
            "period": 120,
        },
        "position": {
            "max_single_pct": 0.35,
            "max_total_pct": 0.9,
        },
    },
}

DEFAULT_STRATEGY = "momentum_monthly"

BACKTEST_CONFIG = {
    "initial_capital": 1000000,
    "commission_rate": 0.0003,
    "benchmark_code": "510300",
    "rebalance_freq_days": 5,
}

WEB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5002,
    "debug": True,
}

PARAM_PRESETS = {
    "多因子轮动": [
    {"name": "🏆 激进高收益型", "params": {"lookback_momentum": 20, "lookback_volatility": 20, "top_n": 5, "rebalance_freq": 10}},
    {"name": "🥇 最优风险调整型", "params": {"lookback_momentum": 20, "lookback_volatility": 20, "top_n": 4, "rebalance_freq": 10}},
    {"name": "🥈 均衡稳健型", "params": {"lookback_momentum": 20, "lookback_volatility": 20, "top_n": 2, "rebalance_freq": 10}},
    {"name": "🥉 最低回撤型", "params": {"lookback_momentum": 20, "lookback_volatility": 20, "top_n": 2, "rebalance_freq": 20}},
    {"name": "📊 低频交易型", "params": {"lookback_momentum": 20, "lookback_volatility": 20, "top_n": 4, "rebalance_freq": 20}},
    {"name": "⚙️ 自定义参数", "params": None},
],
}
