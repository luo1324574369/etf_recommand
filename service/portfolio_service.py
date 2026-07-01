from data.storage.portfolio_repo import PortfolioRepository
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository


class PortfolioService:
    def __init__(self, db):
        self.db = db
        self.repo = PortfolioRepository(db)
        self.etf_repo = ETFRepository(db)
        self.price_repo = PriceRepository(db)

    def create_account(self, initial_capital: float):
        return self.repo.create_account(initial_capital=initial_capital)

    def get_account(self):
        return self.repo.get_account()

    def get_portfolio_overview(self, trade_limit: int = 10):
        account = self.repo.get_account()
        if not account:
            return {
                "account": None,
                "holdings": [],
                "trades": [],
                "etf_name_map": {},
                "total_market_value": 0,
                "total_profit": 0,
                "total_profit_pct": 0,
            }

        holdings = self.repo.get_all_holdings()
        trades = self.repo.list_trades(limit=trade_limit)

        etf_name_map = {}
        price_map = {}
        for h in holdings:
            code = h["code"]
            etf = self.etf_repo.get_etf(code)
            etf_name_map[code] = etf["name"] if etf else code
            latest = self.price_repo.get_latest_price(code)
            price_map[code] = latest["close"] if latest else 0

        for t in trades:
            code = t["code"]
            if code not in etf_name_map:
                etf = self.etf_repo.get_etf(code)
                etf_name_map[code] = etf["name"] if etf else code

        total_mv = sum(h["quantity"] * price_map.get(h["code"], 0) for h in holdings)
        total_profit = (account["cash"] + total_mv) - account["initial_capital"]
        total_profit_pct = total_profit / account["initial_capital"] if account["initial_capital"] > 0 else 0

        holdings_with_profit = []
        for h in holdings:
            code = h["code"]
            qty = h["quantity"]
            cost = h["cost_price"]
            current = price_map.get(code, 0)
            mv = qty * current
            profit = mv - qty * cost
            profit_pct = profit / (qty * cost) if qty * cost > 0 else 0
            holdings_with_profit.append({
                "code": code,
                "name": etf_name_map.get(code, code),
                "quantity": qty,
                "cost_price": cost,
                "current_price": current,
                "market_value": mv,
                "profit": profit,
                "profit_pct": profit_pct,
            })

        return {
            "account": account,
            "holdings": holdings_with_profit,
            "trades": trades,
            "etf_name_map": etf_name_map,
            "total_market_value": total_mv,
            "total_profit": total_profit,
            "total_profit_pct": total_profit_pct,
        }

    def execute_buy(self, code: str, quantity: int, price: float, fee: float = 5, trade_date: str = None):
        account = self.repo.get_account()
        if not account:
            raise ValueError("请先初始化账户")

        total = quantity * price + fee
        if total > account["cash"]:
            raise ValueError(f"现金不足，当前现金 {account['cash']:.2f} 元，需要 {total:.2f} 元")

        return self.repo.execute_buy(
            code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date
        )

    def execute_sell(self, code: str, quantity: int, price: float, fee: float = 5, trade_date: str = None):
        account = self.repo.get_account()
        if not account:
            raise ValueError("请先初始化账户")

        holding = self.repo.get_holding(code)
        if not holding or holding["quantity"] < quantity:
            raise ValueError(f"持仓不足或未持有 {code}")

        return self.repo.execute_sell(
            code=code, quantity=quantity, price=price, fee=fee, trade_date=trade_date
        )

    def list_trades(self, limit: int = 10):
        return self.repo.list_trades(limit=limit)

    def get_holding(self, code: str):
        return self.repo.get_holding(code)

    def get_all_holdings(self):
        return self.repo.get_all_holdings()
