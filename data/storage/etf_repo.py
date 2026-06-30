import sqlite3


class ETFRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def insert_etf(
        self,
        code: str,
        name: str,
        sector: str | None = None,
        etf_type: str | None = None,
        listed_date: str | None = None,
        is_active: int = 1,
    ) -> None:
        self.db.execute(
            """
            INSERT OR REPLACE INTO etf_info (code, name, sector, type, listed_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (code, name, sector, etf_type, listed_date, is_active),
        )
        self.db.commit()

    def batch_insert(self, etfs: list[dict]) -> None:
        self.db.executemany(
            """
            INSERT OR REPLACE INTO etf_info (code, name, sector, type, listed_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    etf["code"],
                    etf["name"],
                    etf.get("sector"),
                    etf.get("type"),
                    etf.get("listed_date"),
                    etf.get("is_active", 1),
                )
                for etf in etfs
            ],
        )
        self.db.commit()

    def get_etf(self, code: str) -> dict | None:
        cursor = self.db.execute(
            "SELECT * FROM etf_info WHERE code = ?",
            (code,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def list_etfs(self, active_only: bool = True) -> list[dict]:
        if active_only:
            cursor = self.db.execute(
                "SELECT * FROM etf_info WHERE is_active = 1 ORDER BY code"
            )
        else:
            cursor = self.db.execute(
                "SELECT * FROM etf_info ORDER BY code"
            )
        return [dict(row) for row in cursor.fetchall()]

    def set_active(self, code: str, is_active: int) -> None:
        self.db.execute(
            "UPDATE etf_info SET is_active = ? WHERE code = ?",
            (is_active, code),
        )
        self.db.commit()
