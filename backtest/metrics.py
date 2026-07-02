class BacktestMetrics:
    """回测指标计算：从 backtrader analyzers 提取 + 自定义补充"""

    @staticmethod
    def calculate(strat, initial_capital) -> dict:
        """计算6个核心指标"""
        final_capital = strat.broker.get_value()
        total_return = (final_capital - initial_capital) / initial_capital

        # 年化收益率
        trading_days = len(strat.data)
        annual_return = (1 + total_return) ** (252 / trading_days) - 1 if trading_days > 0 else 0

        # 从 analyzers 提取
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()

        sharpe_ratio = sharpe.get('sharperatio', 0) or 0
        max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
        trade_count = trades.get('total', {}).get('total', 0)
        won_count = trades.get('won', {}).get('total', 0)
        win_rate = won_count / trade_count if trade_count > 0 else 0

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown / 100,  # backtrader 返回百分比，转小数
            "sharpe_ratio": sharpe_ratio,
            "win_rate": win_rate,
            "trade_count": trade_count,
        }
