import sqlite3
from datetime import datetime


class PortfolioRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self.db.row_factory = sqlite3.Row

    def create_account(self, initial_capital: float) -> dict:
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO account (initial_capital, cash)
            VALUES (?, ?)
            """,
            (initial_capital, initial_capital),
        )
        self.db.commit()
        return {
            "id": cur.lastrowid,
            "initial_capital": initial_capital,
            "cash": initial_capital,
        }

    def get_account(self) -> dict | None:
        cur = self.db.cursor()
        cur.execute("SELECT * FROM account LIMIT 1")
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def update_cash(self, new_cash: float) -> None:
        cur = self.db.cursor()
        cur.execute(
            """
            UPDATE account SET cash = ?, updated_at = ?
            WHERE id = 1
            """,
            (new_cash, datetime.now().isoformat()),
        )
        self.db.commit()

    def add_trade(self, trade: dict) -> int:
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT INTO trade (trade_date, code, direction, quantity, price, fee, note)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade["trade_date"],
                trade["code"],
                trade["direction"],
                trade["quantity"],
                trade["price"],
                trade.get("fee", 0),
                trade.get("note"),
            ),
        )
        self.db.commit()
        return cur.lastrowid

    def list_trades(self, limit: int = 10) -> list:
        cur = self.db.cursor()
        cur.execute(
            """
            SELECT * FROM trade
            ORDER BY trade_date DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_trades_by_code(self, code: str) -> list:
        cur = self.db.cursor()
        cur.execute(
            """
            SELECT * FROM trade
            WHERE code = ?
            ORDER BY trade_date DESC
            """,
            (code,),
        )
        return [dict(row) for row in cur.fetchall()]
