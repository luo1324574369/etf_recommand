import os
import sys

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config.settings import DB_PATH
from data.storage.db import get_db
from service.portfolio_service import PortfolioService
from presentation.cli.portfolio import render_account_summary, render_holdings, render_recent_trades


def main():
    conn = get_db(str(DB_PATH))
    try:
        svc = PortfolioService(conn)
        ov = svc.get_portfolio_overview(trade_limit=10)

        if not ov["account"]:
            print("\n请先初始化账户: python -m presentation.cli.init_account\n")
            return

        price_map = {}
        for h in ov["holdings"]:
            price_map[h["code"]] = h["current_price"]

        render_account_summary(ov["account"], ov["total_market_value"])
        render_holdings(
            [{"code": h["code"], "quantity": h["quantity"], "cost_price": h["cost_price"]}
             for h in ov["holdings"]],
            ov["etf_name_map"],
            price_map,
        )
        render_recent_trades(ov["trades"], ov["etf_name_map"])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
