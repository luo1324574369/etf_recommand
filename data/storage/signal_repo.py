import json
import sqlite3


class SignalRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def save_signal(self, signal_date, strategy_name, code, name=None, rank=None, score=None, reason=None, action=None) -> int:
        if not signal_date:
            raise ValueError("signal_date 不能为空")
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
        with self.db:
            for signal in signals:
                if not signal.get("signal_date"):
                    raise ValueError("signal_date 不能为空")
                reason = signal.get("reason")
                reason_str = json.dumps(reason, ensure_ascii=False) if isinstance(reason, dict) else reason
                self.db.execute(
                    """
                    INSERT INTO strategy_signal
                        (signal_date, strategy_name, code, name, rank, score, reason, action)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal["signal_date"], signal["strategy_name"], signal["code"],
                        signal.get("name"), signal.get("rank"), signal.get("score"),
                        reason_str, signal.get("action"),
                    ),
                )
        return len(signals)

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

    def delete_signals_by_date(self, strategy_name, signal_date) -> int:
        """删除指定日期的旧信号，返回删除条数"""
        cursor = self.db.execute(
            "DELETE FROM strategy_signal WHERE strategy_name = ? AND signal_date = ?",
            (strategy_name, signal_date)
        )
        self.db.commit()
        return cursor.rowcount

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
