import backtrader as bt


class MomentumBTStrategy(bt.Strategy):
    """周频买入 + 日频检查卖出，等权分配"""

    params = (
        ('strategy_engine', None),   # 注入现有 StrategyEngine
        ('price_repo', None),
        ('etf_codes', []),
        ('rebalance_freq', 5),       # 每5个交易日调仓
        ('top_n', 5),
        ('commission_rate', 0.0003),
    )

    def __init__(self):
        self.day_count = 0
        self.trade_records = []
        self.daily_nav = []  # 每日记录 {date, nav}

    def next(self):
        self.day_count += 1
        current_date = self.data.datetime.date(0).strftime('%Y-%m-%d')

        # 记录每日净值（关键：必须在 next() 中实时记录）
        self.daily_nav.append({
            "date": current_date,
            "nav": self.broker.get_value() / self.broker.startingcash,
        })

        # 日频：检查卖出信号
        holdings = self._get_holdings()
        if holdings:
            sell_signals = self.p.strategy_engine.check_exit(
                holdings, current_date, self.p.price_repo)
            for sig in sell_signals:
                self._execute_sell(sig['code'], sig['current_price'])

        # 周频：调仓买入
        if self.day_count % self.p.rebalance_freq == 0:
            signals = self.p.strategy_engine.run(
                self.p.etf_codes, current_date, self.p.price_repo)
            self._rebalance_equal_weight(signals)

    def notify_order(self, order):
        """记录订单成交（买卖方向、数量、价格、手续费）"""
        if order.status == order.Completed:
            self.trade_records.append({
                "trade_date": self.data.datetime.date(0).strftime('%Y-%m-%d'),
                "code": order.data._name,
                "direction": "buy" if order.isbuy() else "sell",
                "quantity": order.executed.size,
                "price": order.executed.price,
                "commission": order.executed.comm,
            })

    def _get_holdings(self) -> dict:
        """获取当前持仓（供 check_exit 使用）"""
        holdings = {}
        for data in self.datas:
            position = self.getposition(data)
            if position.size > 0:
                holdings[data._name] = {
                    'shares': position.size,
                    'cost_basis': position.price,
                }
        return holdings

    def _rebalance_equal_weight(self, signals):
        """等权分配：先清仓不在信号中的持仓，再等权买入信号标的"""
        target_codes = {s['code'] for s in signals}
        # 清仓非目标持仓
        for data in self.datas:
            if data._name not in target_codes:
                position = self.getposition(data)
                if position.size > 0:
                    self.close(data)
        # 等权买入
        if not signals:
            return
        per_value = self.broker.get_value() / len(signals)
        for sig in signals:
            data = self._get_data_by_name(sig['code'])
            if data is None:
                continue
            price = data.close[0]
            if price <= 0:
                continue
            qty = int(per_value / price / 100) * 100  # 按手取整
            if qty > 0:
                self.buy(data, size=qty)

    def _execute_sell(self, code, price):
        data = self._get_data_by_name(code)
        if data is None:
            return
        self.close(data)

    def _get_data_by_name(self, code):
        for data in self.datas:
            if data._name == code:
                return data
        return None


class BuyAndHoldBTStrategy(bt.Strategy):
    """买入持有基准策略"""

    params = (
        ('target_code', '510300'),  # 沪深300
    )

    def __init__(self):
        self.bought = False
        self.daily_nav = []  # 每日记录 {date, nav}

    def next(self):
        current_date = self.data.datetime.date(0).strftime('%Y-%m-%d')
        self.daily_nav.append({
            "date": current_date,
            "nav": self.broker.get_value() / self.broker.startingcash,
        })
        if not self.bought:
            data = self._get_data_by_name(self.p.target_code)
            if data is not None:
                qty = int(self.broker.get_cash() / data.close[0] / 100) * 100
                if qty > 0:
                    self.buy(data, size=qty)
                self.bought = True

    def _get_data_by_name(self, code):
        for data in self.datas:
            if data._name == code:
                return data
        return None
