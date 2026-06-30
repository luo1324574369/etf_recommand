import sqlite3


class PriceRepository:

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def insert_daily_price(self, code: str, data: list[dict]) -> int:
        if not data:
            return 0

        rows = [
            (
                code,
                item["trade_date"],
                item.get("open"),
                item.get("high"),
                item.get("low"),
                item["close"],
                item.get("volume"),
                item.get("amount"),
            )
            for item in data
        ]

        cur = self.db.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO etf_daily_price
                (code, trade_date, open, high, low, close, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.db.commit()
        return cur.rowcount

    def batch_insert(self, prices_by_code: dict[str, list[dict]]) -> int:
        total = 0
        for code, data in prices_by_code.items():
            total += self.insert_daily_price(code, data)
        return total

    def get_daily_price(
        self, code: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        query = "SELECT * FROM etf_daily_price WHERE code = ?"
        params: list = [code]

        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)

        query += " ORDER BY trade_date"

        cur = self.db.cursor()
        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def get_latest_date(self, code: str) -> str | None:
        cur = self.db.cursor()
        cur.execute(
            "SELECT MAX(trade_date) FROM etf_daily_price WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None

    def get_latest_price(self, code: str) -> dict | None:
        cur = self.db.cursor()
        cur.execute(
            """
            SELECT * FROM etf_daily_price
            WHERE code = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
