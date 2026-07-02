from dataclasses import dataclass, field


@dataclass
class TradeRecord:
    """单笔交易记录"""
    trade_date: str
    code: str
    direction: str  # "buy" | "sell"
    quantity: int
    price: float
    commission: float


@dataclass
class BacktestResult:
    """单次回测结果"""
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    daily_nav: list[dict]          # [{"date": "2025-01-01", "nav": 1.02}, ...]
    trades: list[TradeRecord]
    final_holdings: list[dict]     # [{"code": "510300", "quantity": 1000, "last_price": 4.5}, ...]
    metrics: dict                  # 6个核心指标
    is_benchmark: bool = False     # 是否基准
