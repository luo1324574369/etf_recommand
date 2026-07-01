import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data" / "etf.db"

ETF_UNIVERSE = [
    {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "指数"},
    {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "指数"},
    {"code": "159915", "name": "创业板ETF", "sector": "宽基", "type": "指数"},
    {"code": "588000", "name": "科创50ETF", "sector": "宽基", "type": "指数"},
    {"code": "159928", "name": "消费ETF", "sector": "消费", "type": "行业"},
    {"code": "512690", "name": "酒ETF", "sector": "消费", "type": "行业"},
    {"code": "159992", "name": "创新药ETF", "sector": "医药", "type": "行业"},
    {"code": "512010", "name": "医药ETF", "sector": "医药", "type": "行业"},
    {"code": "515030", "name": "新能源车ETF", "sector": "新能源", "type": "行业"},
    {"code": "515790", "name": "光伏ETF", "sector": "新能源", "type": "行业"},
    {"code": "159995", "name": "芯片ETF", "sector": "科技", "type": "行业"},
    {"code": "515000", "name": "科技ETF", "sector": "科技", "type": "行业"},
    {"code": "512480", "name": "半导体ETF", "sector": "科技", "type": "行业"},
    {"code": "512660", "name": "军工ETF", "sector": "军工", "type": "行业"},
    {"code": "512880", "name": "证券ETF", "sector": "金融", "type": "行业"},
    {"code": "512000", "name": "券商ETF", "sector": "金融", "type": "行业"},
    {"code": "510050", "name": "上证50ETF", "sector": "宽基", "type": "指数"},
    {"code": "159825", "name": "农业ETF", "sector": "周期", "type": "行业"},
    {"code": "515210", "name": "钢铁ETF", "sector": "周期", "type": "行业"},
    {"code": "159985", "name": "豆粕ETF", "sector": "商品", "type": "商品"},
    {"code": "518880", "name": "黄金ETF", "sector": "商品", "type": "商品"},
    {"code": "159805", "name": "传媒ETF", "sector": "传媒", "type": "行业"},
    {"code": "512980", "name": "传媒ETF", "sector": "传媒", "type": "行业"},
    {"code": "159996", "name": "家电ETF", "sector": "消费", "type": "行业"},
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
    }
}

DEFAULT_STRATEGY = "momentum_weekly"

WEB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5002,
    "debug": True,
}
