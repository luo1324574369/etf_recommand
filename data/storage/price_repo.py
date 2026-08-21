import sqlite3


class PriceRepository:

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def insert_daily_price(self, code: str, data: list[dict]) -> int:
        if not data:
            return 0

        rows = []
        for item in data:
            factor, adjustment_status = self._resolve_adjustment(item)
            raw_open = item.get("open")
            raw_high = item.get("high")
            raw_low = item.get("low")
            raw_close = item["close"]
            rows.append((
                code,
                item["trade_date"],
                raw_open,
                raw_high,
                raw_low,
                raw_close,
                factor,
                item.get("signal_open", raw_open * factor if raw_open is not None else None),
                item.get("signal_high", raw_high * factor if raw_high is not None else None),
                item.get("signal_low", raw_low * factor if raw_low is not None else None),
                item.get("signal_close", raw_close * factor),
                adjustment_status,
                item.get("adjustment_source"),
                item.get("volume"),
                item.get("amount"),
            ))

        cur = self.db.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO etf_daily_price
                (code, trade_date, open, high, low, close, adj_factor,
                 signal_open, signal_high, signal_low, signal_close,
                 adjustment_status, adjustment_source, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.db.commit()
        return cur.rowcount

    @staticmethod
    def _normalise_adj_factor(value) -> float:
        try:
            factor = float(value) if value is not None else 1.0
        except (TypeError, ValueError):
            factor = 1.0
        return factor if factor > 0 else 1.0

    @classmethod
    def _resolve_adjustment(cls, item: dict) -> tuple[float, str]:
        if "adj_factor" not in item or item.get("adj_factor") is None:
            return 1.0, "unavailable"
        try:
            factor = float(item["adj_factor"])
        except (TypeError, ValueError):
            return 1.0, "invalid"
        if factor <= 0:
            return 1.0, "invalid"
        return factor, str(item.get("adjustment_status") or "provided")

    def batch_insert(self, prices_by_code: dict[str, list[dict]]) -> int:
        total = 0
        for code, data in prices_by_code.items():
            total += self.insert_daily_price(code, data)
        return total

    def get_daily_price(
        self, code: str, start_date: str | None = None, end_date: str | None = None,
        adjusted: bool = False,
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
        rows = [dict(row) for row in cur.fetchall()]
        if adjusted:
            return [self._as_signal_price(row) for row in rows]
        return rows

    @staticmethod
    def _as_signal_price(row: dict) -> dict:
        signal_row = dict(row)
        signal_row["raw_open"] = signal_row.get("open")
        signal_row["raw_high"] = signal_row.get("high")
        signal_row["raw_low"] = signal_row.get("low")
        signal_row["raw_close"] = signal_row.get("close")
        for raw_name in ("open", "high", "low", "close"):
            signal_name = f"signal_{raw_name}"
            if signal_row.get("adjustment_status") == "provided" and signal_row.get(signal_name) is not None:
                signal_row[raw_name] = signal_row[signal_name]
        return signal_row

    def get_signal_price(
        self, code: str, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        return self.get_daily_price(code, start_date, end_date, adjusted=True)

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
