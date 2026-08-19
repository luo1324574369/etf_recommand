import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "data" / "etf.db"


def _load_dotenv():
    """从 .env 文件加载环境变量（不引入 python-dotenv 依赖）"""
    env_path = BASE_DIR / '.env'
    if not env_path.exists():
        return
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key, value = key.strip(), value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value


_load_dotenv()

# Tushare token 从 .env 或环境变量读取，不硬编码到代码中
TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', '')

ETF_UNIVERSE = [
    # 宽基指数（删除创业板/科创板有门槛标的，保留 51/56 开头沪深主板）
    {"code": "510300", "name": "沪深300ETF", "sector": "宽基", "type": "指数", "ts_code": "510300.SH"},
    {"code": "510500", "name": "中证500ETF", "sector": "宽基", "type": "指数", "ts_code": "510500.SH"},
    {"code": "510050", "name": "上证50ETF", "sector": "宽基", "type": "指数", "ts_code": "510050.SH"},
    {"code": "510310", "name": "沪深300ETF易方达", "sector": "宽基", "type": "指数", "ts_code": "510310.SH"},
    {"code": "512100", "name": "中证1000ETF", "sector": "宽基", "type": "指数", "ts_code": "512100.SH"},
    {"code": "512040", "name": "沪深300价值ETF", "sector": "宽基", "type": "指数", "ts_code": "512040.SH"},
    {"code": "560050", "name": "上证50ETF华安", "sector": "宽基", "type": "指数", "ts_code": "560050.SH"},
    {"code": "511030", "name": "沪深300ETF华泰柏瑞", "sector": "宽基", "type": "指数", "ts_code": "511030.SH"},
    # 消费（原3只 + 新增1只 = 4只）
    {"code": "159928", "name": "消费ETF", "sector": "消费", "type": "行业", "ts_code": "159928.SZ"},
    {"code": "512690", "name": "酒ETF", "sector": "消费", "type": "行业", "ts_code": "512690.SH"},
    {"code": "159996", "name": "家电ETF", "sector": "消费", "type": "行业", "ts_code": "159996.SZ"},
    {"code": "560880", "name": "家电ETF龙头", "sector": "消费", "type": "行业", "ts_code": "560880.SH"},
    # 医药（原2只 + 新增2只 = 4只）
    {"code": "159992", "name": "创新药ETF", "sector": "医药", "type": "行业", "ts_code": "159992.SZ"},
    {"code": "512010", "name": "医药ETF", "sector": "医药", "type": "行业", "ts_code": "512010.SH"},
    {"code": "512170", "name": "医疗ETF", "sector": "医药", "type": "行业", "ts_code": "512170.SH"},
    {"code": "515120", "name": "创新药ETF沪港深", "sector": "医药", "type": "行业", "ts_code": "515120.SH"},
    # 新能源（原2只 + 新增3只 = 5只）
    {"code": "515030", "name": "新能源车ETF", "sector": "新能源", "type": "行业", "ts_code": "515030.SH"},
    {"code": "515790", "name": "光伏ETF", "sector": "新能源", "type": "行业", "ts_code": "515790.SH"},
    {"code": "159755", "name": "电池ETF", "sector": "新能源", "type": "行业", "ts_code": "159755.SZ"},
    {"code": "159863", "name": "光伏ETF", "sector": "新能源", "type": "行业", "ts_code": "159863.SZ"},
    {"code": "516160", "name": "新能源车ETF", "sector": "新能源", "type": "行业", "ts_code": "516160.SH"},
    # 科技（原3只 + 新增1只 = 4只）
    {"code": "159995", "name": "芯片ETF", "sector": "科技", "type": "行业", "ts_code": "159995.SZ"},
    {"code": "515000", "name": "科技ETF", "sector": "科技", "type": "行业", "ts_code": "515000.SH"},
    {"code": "512480", "name": "半导体ETF", "sector": "科技", "type": "行业", "ts_code": "512480.SH"},
    {"code": "515050", "name": "5GETF", "sector": "科技", "type": "行业", "ts_code": "515050.SH"},
    # 金融（原3只 + 新增2只 = 5只）
    {"code": "512880", "name": "证券ETF", "sector": "金融", "type": "行业", "ts_code": "512880.SH"},
    {"code": "512000", "name": "券商ETF", "sector": "金融", "type": "行业", "ts_code": "512000.SH"},
    {"code": "512800", "name": "银行ETF", "sector": "金融", "type": "行业", "ts_code": "512800.SH"},
    {"code": "512990", "name": "保险主题ETF", "sector": "金融", "type": "行业", "ts_code": "512990.SH"},
    {"code": "159841", "name": "银行ETF", "sector": "金融", "type": "行业", "ts_code": "159841.SZ"},
    # 周期（原5只）
    {"code": "159825", "name": "农业ETF", "sector": "周期", "type": "行业", "ts_code": "159825.SZ"},
    {"code": "515210", "name": "钢铁ETF", "sector": "周期", "type": "行业", "ts_code": "515210.SH"},
    {"code": "515220", "name": "煤炭ETF", "sector": "周期", "type": "行业", "ts_code": "515220.SH"},
    {"code": "512400", "name": "有色金属ETF", "sector": "周期", "type": "行业", "ts_code": "512400.SH"},
    {"code": "512200", "name": "房地产ETF", "sector": "周期", "type": "行业", "ts_code": "512200.SH"},
    # 商品（原2只）
    {"code": "159985", "name": "豆粕ETF", "sector": "商品", "type": "商品", "ts_code": "159985.SZ"},
    {"code": "518880", "name": "黄金ETF", "sector": "商品", "type": "商品", "ts_code": "518880.SH"},
    # 红利（原2只）
    {"code": "510880", "name": "红利ETF", "sector": "红利", "type": "指数", "ts_code": "510880.SH"},
    {"code": "512890", "name": "红利低波ETF", "sector": "红利", "type": "指数", "ts_code": "512890.SH"},
    # 军工（原1只 + 新增1只 = 2只）
    {"code": "512660", "name": "军工ETF", "sector": "军工", "type": "行业", "ts_code": "512660.SH"},
    {"code": "512680", "name": "军工ETF", "sector": "军工", "type": "行业", "ts_code": "512680.SH"},
    # 传媒（原2只 + 新增2只 = 4只）
    {"code": "159805", "name": "传媒ETF", "sector": "传媒", "type": "行业", "ts_code": "159805.SZ"},
    {"code": "512980", "name": "传媒ETF", "sector": "传媒", "type": "行业", "ts_code": "512980.SH"},
    {"code": "159869", "name": "游戏ETF", "sector": "传媒", "type": "行业", "ts_code": "159869.SZ"},
    {"code": "516010", "name": "游戏ETF", "sector": "传媒", "type": "行业", "ts_code": "516010.SH"},
    # 海外（原2只）
    {"code": "159920", "name": "恒生ETF", "sector": "海外", "type": "指数", "ts_code": "159920.SZ"},
    {"code": "513100", "name": "纳指ETF", "sector": "海外", "type": "指数", "ts_code": "513100.SH"},
    # 国企改革（新增1只）
    {"code": "512950", "name": "央企改革ETF", "sector": "国企改革", "type": "行业", "ts_code": "512950.SH"},
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
    {"name": "🏆 收益优先型", "params": {"lookback_momentum": 60, "top_n": 3, "rebalance_freq": 60, "sector_penalty_factor": 0.5, "lookback_volatility": 60, "sector_exclude_threshold": -0.15, "max_monthly_turnover": 60.0, "drawdown_threshold": 35.0, "max_sector_exposure_pct": 100.0, "market_regime_switch": True, "enable_factor_monitor": True}},
    {"name": "⚖️ 均衡型", "params": {"lookback_momentum": 60, "top_n": 4, "rebalance_freq": 60, "sector_penalty_factor": 0.7, "lookback_volatility": 60, "sector_exclude_threshold": -0.15, "max_monthly_turnover": 60.0, "drawdown_threshold": 35.0, "max_sector_exposure_pct": 100.0, "market_regime_switch": True, "enable_factor_monitor": True}},
    {"name": "🛡️ 低回撤型", "params": {"lookback_momentum": 60, "top_n": 3, "rebalance_freq": 20, "sector_penalty_factor": 0.7, "lookback_volatility": 60, "sector_exclude_threshold": -0.15, "max_monthly_turnover": 60.0, "drawdown_threshold": 35.0, "max_sector_exposure_pct": 100.0, "market_regime_switch": True, "enable_factor_monitor": True}},
    {"name": "📊 低频交易型", "params": {"lookback_momentum": 60, "top_n": 3, "rebalance_freq": 20, "sector_penalty_factor": 1.0, "lookback_volatility": 60, "sector_exclude_threshold": -0.15, "max_monthly_turnover": 60.0, "drawdown_threshold": 35.0, "max_sector_exposure_pct": 100.0, "market_regime_switch": True, "enable_factor_monitor": True}},
    {"name": "⚙️ 自定义参数", "params": None},
],
}


