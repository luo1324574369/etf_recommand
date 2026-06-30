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
        "factors": [
            {"name": "momentum_20d", "weight": 0.4},
            {"name": "momentum_60d", "weight": 0.3},
            {"name": "volatility_20d", "weight": 0.3},
        ],
        "filters": [
            {"name": "price_above_ma20", "enabled": True},
            {"name": "volume_confirm", "enabled": True},
        ],
        "score_weights": {
            "momentum": 0.6,
            "quality": 0.2,
            "value": 0.2,
        },
        "exit_rules": [
            {"name": "stop_loss", "threshold": -0.08},
            {"name": "take_profit", "threshold": 0.20},
            {"name": "trailing_stop", "threshold": -0.05},
        ],
        "position": {
            "max_positions": 5,
            "equal_weight": True,
            "rebalance_freq": "weekly",
        },
    }
}

DEFAULT_STRATEGY = "momentum_weekly"

WEB_CONFIG = {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": True,
}
