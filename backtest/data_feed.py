import backtrader as bt
from datetime import datetime


class SQLiteDataFeed(bt.feeds.DataBase):
    """从 PriceRepository 读取 OHLCV 数据的自定义 DataFeed"""

    params = (
        ('code', ''),
        ('price_repo', None),
    )

    def __init__(self):
        super().__init__()
        self._data = None
        self._index = 0

    def start(self):
        super().start()
        rows = self.params.price_repo.get_daily_price(
            code=self.params.code,
            start_date=self.p.fromdate.strftime('%Y-%m-%d') if self.p.fromdate else None,
            end_date=self.p.todate.strftime('%Y-%m-%d') if self.p.todate else None,
        )
        self._data = rows

    def _load(self):
        if self._index >= len(self._data):
            return False
        row = self._data[self._index]
        dt = datetime.strptime(row['trade_date'], '%Y-%m-%d')
        self.lines.datetime[0] = self.date2num(dt)
        self.lines.open[0] = row['open']
        self.lines.high[0] = row['high']
        self.lines.low[0] = row['low']
        self.lines.close[0] = row['close']
        self.lines.volume[0] = row['volume'] or 0
        self.lines.openinterest[0] = 0
        self._index += 1
        return True
