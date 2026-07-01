import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_PATH
from data.storage.db import get_db
from data.storage.portfolio_repo import PortfolioRepository
from data.storage.etf_repo import ETFRepository
from data.storage.price_repo import PriceRepository
from presentation.cli.portfolio import render_account_summary, render_holdings, render_recent_trades


def main():
    conn = get_db(str(DB_PATH))
    repo = PortfolioRepository(conn)
    etf_repo = ETFRepository(conn)
    price_repo = PriceRepository(conn)

    account = repo.get_account()
    if not account:
        print("\n请先初始化账户: python scripts/init_account.py\n")
        conn.close()
        return

    holdings = repo.get_all_holdings()
    trades = repo.list_trades(limit=10)

    etf_name_map = {}
    price_map = {}
    for h in holdings:
        code = h["code"]
        etf = etf_repo.get_etf(code)
        etf_name_map[code] = etf["name"] if etf else code
        latest = price_repo.get_latest_price(code)
        price_map[code] = latest["close"] if latest else 0

    for t in trades:
        code = t["code"]
        if code not in etf_name_map:
            etf = etf_repo.get_etf(code)
            etf_name_map[code] = etf["name"] if etf else code

    total_mv = sum(h["quantity"] * price_map.get(h["code"], 0) for h in holdings)

    render_account_summary(account, total_mv)
    render_holdings(holdings, etf_name_map, price_map)
    render_recent_trades(trades, etf_name_map)

    conn.close()


if __name__ == "__main__":
    main()
