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
