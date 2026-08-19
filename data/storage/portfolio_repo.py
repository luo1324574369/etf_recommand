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
        self._set_cash(new_cash)
        self.db.commit()

    def add_trade(self, trade: dict) -> int:
        trade_id = self._insert_trade(trade)
        self.db.commit()
        return trade_id

    def _insert_trade(self, trade: dict) -> int:
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
        return cur.lastrowid

    def _set_cash(self, new_cash: float) -> None:
        self.db.execute(
            """
            UPDATE account SET cash = ?, updated_at = ?
            WHERE id = 1
            """,
            (new_cash, datetime.now().isoformat()),
        )

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
        self._upsert_holding(code, quantity, cost_price)
        self.db.commit()

    def delete_holding(self, code: str) -> None:
        self._delete_holding(code)
        self.db.commit()

    def _upsert_holding(self, code: str, quantity: int, cost_price: float) -> None:
        cur = self.db.cursor()
        existing = self.get_holding(code)
        if existing is None:
            if quantity <= 0:
                raise ValueError("新持仓数量必须大于0")
            cur.execute(
                """
                INSERT INTO holding (account_id, code, quantity, cost_price)
                VALUES (1, ?, ?, ?)
                """,
                (code, quantity, cost_price),
            )
            return

        old_qty = existing["quantity"]
        old_cost = existing["cost_price"]
        new_qty = old_qty + quantity
        if new_qty <= 0:
            self._delete_holding(code)
            return
        new_cost = (old_qty * old_cost + quantity * cost_price) / new_qty
        cur.execute(
            """
            UPDATE holding SET quantity = ?, cost_price = ?, updated_at = ?
            WHERE account_id = 1 AND code = ?
            """,
            (new_qty, new_cost, datetime.now().isoformat(), code),
        )

    def _delete_holding(self, code: str) -> None:
        self.db.execute(
            "DELETE FROM holding WHERE account_id = 1 AND code = ?",
            (code,),
        )

    def execute_buy(self, code: str, quantity: int, price: float, fee: float, trade_date: str) -> None:
        if quantity <= 0 or price < 0 or fee < 0:
            raise ValueError("买入参数无效")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            account = self.get_account()
            if account is None:
                raise ValueError("账户不存在")
            total = quantity * price + fee
            if account["cash"] < total:
                raise ValueError("现金余额不足")
            self._insert_trade({
                "trade_date": trade_date,
                "code": code,
                "direction": "buy",
                "quantity": quantity,
                "price": price,
                "fee": fee,
            })
            self._upsert_holding(code=code, quantity=quantity, cost_price=price)
            self._set_cash(account["cash"] - total)

    def execute_sell(self, code: str, quantity: int, price: float, fee: float, trade_date: str) -> None:
        if quantity <= 0 or price < 0 or fee < 0:
            raise ValueError("卖出参数无效")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            account = self.get_account()
            holding = self.get_holding(code)
            if account is None:
                raise ValueError("账户不存在")
            if holding is None or holding["quantity"] < quantity:
                raise ValueError("持仓数量不足")
            self._insert_trade({
                "trade_date": trade_date,
                "code": code,
                "direction": "sell",
                "quantity": quantity,
                "price": price,
                "fee": fee,
            })
            self._upsert_holding(code=code, quantity=-quantity, cost_price=holding["cost_price"])
            self._set_cash(account["cash"] + quantity * price - fee)
