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

    def get_holding(self, code: str) -> dict | None:
        cur = self.db.cursor()
        cur.execute(
            "SELECT * FROM holding WHERE account_id = 1 AND code = ?",
            (code,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def get_all_holdings(self) -> list:
        cur = self.db.cursor()
        cur.execute("SELECT * FROM holding WHERE account_id = 1")
        return [dict(row) for row in cur.fetchall()]

    def update_holding(self, code: str, quantity: int, cost_price: float) -> None:
        cur = self.db.cursor()
        existing = self.get_holding(code)

        if existing is None:
            cur.execute(
                """
                INSERT INTO holding (account_id, code, quantity, cost_price)
                VALUES (1, ?, ?, ?)
                """,
                (code, quantity, cost_price),
            )
        else:
            old_qty = existing["quantity"]
            old_cost = existing["cost_price"]
            new_qty = old_qty + quantity
            if new_qty <= 0:
                self.delete_holding(code)
            else:
                new_cost = (old_qty * old_cost + quantity * cost_price) / new_qty
                cur.execute(
                    """
                    UPDATE holding SET quantity = ?, cost_price = ?, updated_at = ?
                    WHERE account_id = 1 AND code = ?
                    """,
                    (new_qty, new_cost, datetime.now().isoformat(), code),
                )
        self.db.commit()

    def delete_holding(self, code: str) -> None:
        cur = self.db.cursor()
        cur.execute(
            "DELETE FROM holding WHERE account_id = 1 AND code = ?",
            (code,),
        )
        self.db.commit()
