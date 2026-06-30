import json
import sqlite3


class SignalRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def save_signal(self, signal_date, strategy_name, code, name=None, rank=None, score=None, reason=None, action=None) -> int:
        reason_str = json.dumps(reason, ensure_ascii=False) if isinstance(reason, dict) else reason
        cursor = self.db.execute(
            """
            INSERT INTO strategy_signal (signal_date, strategy_name, code, name, rank, score, reason, action)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (signal_date, strategy_name, code, name, rank, score, reason_str, action)
        )
        self.db.commit()
        return cursor.lastrowid

    def batch_save_signals(self, signals: list[dict]) -> int:
        count = 0
        for signal in signals:
            self.save_signal(**signal)
            count += 1
        return count

    def get_latest_signals(self, strategy_name, limit=None) -> list[dict]:
        row = self.db.execute(
            "SELECT MAX(signal_date) as latest_date FROM strategy_signal WHERE strategy_name = ?",
            (strategy_name,)
        ).fetchone()
        if not row or not row["latest_date"]:
            return []
        latest_date = row["latest_date"]
        return self.get_signals_by_date(strategy_name, latest_date, limit)

    def get_signals_by_date(self, strategy_name, signal_date, limit=None) -> list[dict]:
        query = """
            SELECT * FROM strategy_signal
            WHERE strategy_name = ? AND signal_date = ?
            ORDER BY rank
        """
        params = [strategy_name, signal_date]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self.db.execute(query, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("reason"):
                try:
                    d["reason"] = json.loads(d["reason"])
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append(d)
        return result

    def list_signal_dates(self, strategy_name, limit=20) -> list[str]:
        rows = self.db.execute(
            """
            SELECT DISTINCT signal_date FROM strategy_signal
            WHERE strategy_name = ?
            ORDER BY signal_date DESC
            LIMIT ?
            """,
            (strategy_name, limit)
        ).fetchall()
        return [row["signal_date"] for row in rows]
