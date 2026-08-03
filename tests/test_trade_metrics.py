"""测试 _compute_trade_metrics_from_log 指标计算"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.backtest_utils import _compute_trade_metrics_from_log, _compute_avg_hold_days_from_log


def test_num_trades_equals_log_length():
    """交易次数等于trade_log长度（每次下单算1笔）"""
    trade_list = [
        {'date': '2024-01-01', 'code': '510300', 'direction': '买入', 'quantity': 100,
         'price': 4.0, 'amount': 400.0, 'fee': 0.12, 'pnl': 0.0, 'trade_type': 'satellite',
         'total_value': 1000000},
        {'date': '2024-02-01', 'code': '510300', 'direction': '卖出', 'quantity': 100,
         'price': 4.5, 'amount': 450.0, 'fee': 0.135, 'pnl': 50.0, 'trade_type': 'satellite',
         'total_value': 1000500},
    ]
    metrics = _compute_trade_metrics_from_log(trade_list, initial_capital=1000000, years=1)
    assert metrics['num_trades'] == 2  # 买入1笔 + 卖出1笔


def test_win_rate_only_counts_sells():
    """胜率只统计卖出笔（买入pnl=0不参与）"""
    trade_list = [
        {'date': '2024-01-01', 'code': '510300', 'direction': '买入', 'quantity': 100,
         'price': 4.0, 'amount': 400.0, 'fee': 0.12, 'pnl': 0.0, 'trade_type': 'satellite',
         'total_value': 1000000},
        {'date': '2024-02-01', 'code': '510300', 'direction': '卖出', 'quantity': 100,
         'price': 4.5, 'amount': 450.0, 'fee': 0.135, 'pnl': 50.0, 'trade_type': 'satellite',
         'total_value': 1000500},
        {'date': '2024-02-01', 'code': '510500', 'direction': '买入', 'quantity': 100,
         'price': 5.0, 'amount': 500.0, 'fee': 0.15, 'pnl': 0.0, 'trade_type': 'satellite',
         'total_value': 1000500},
        {'date': '2024-03-01', 'code': '510500', 'direction': '卖出', 'quantity': 100,
         'price': 4.8, 'amount': 480.0, 'fee': 0.144, 'pnl': -20.0, 'trade_type': 'satellite',
         'total_value': 1000300},
    ]
    metrics = _compute_trade_metrics_from_log(trade_list, initial_capital=1000000, years=1)
    # 2笔卖出，1笔盈利 → 胜率50%
    assert metrics['win_rate'] == 50.0
    assert metrics['profit_factor'] == 50.0 / 20.0  # 2.5


def test_core_build_excluded_from_turnover():
    """核心建仓不计入换手率"""
    trade_list = [
        {'date': '2024-01-01', 'code': '510300', 'direction': '买入', 'quantity': 10000,
         'price': 4.0, 'amount': 40000.0, 'fee': 12.0, 'pnl': 0.0, 'trade_type': 'core',
         'total_value': 1000000},
        {'date': '2024-02-01', 'code': '510500', 'direction': '买入', 'quantity': 1000,
         'price': 5.0, 'amount': 5000.0, 'fee': 1.5, 'pnl': 0.0, 'trade_type': 'satellite',
         'total_value': 1000000},
    ]
    metrics = _compute_trade_metrics_from_log(trade_list, initial_capital=1000000, years=1)
    # 仅卫星买入5000元计入换手率，核心40000元不计入
    assert metrics['turnover_total_pct'] == 0.5  # 5000/1000000*100


def test_avg_hold_days_fifo_pairing():
    """平均持仓天数按FIFO配对"""
    trade_list = [
        {'date': '2024-01-01', 'code': '510300', 'direction': '买入', 'quantity': 100,
         'price': 4.0, 'amount': 400.0, 'fee': 0.12, 'pnl': 0.0, 'trade_type': 'satellite',
         'total_value': 1000000},
        {'date': '2024-03-01', 'code': '510300', 'direction': '卖出', 'quantity': 100,
         'price': 4.5, 'amount': 450.0, 'fee': 0.135, 'pnl': 50.0, 'trade_type': 'satellite',
         'total_value': 1000500},
    ]
    avg_hold = _compute_avg_hold_days_from_log(trade_list)
    # 1月1日到3月1日 = 60天
    assert avg_hold == 60
