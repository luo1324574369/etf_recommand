"""行情快照及质量报告持久化。"""

import json
import sqlite3

from data.contracts import DataQualityReport, MarketDataSnapshot


class MarketDataRepository:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def save_snapshot(self, snapshot: MarketDataSnapshot, report: DataQualityReport) -> str:
        self.db.execute(
            """
            INSERT OR REPLACE INTO market_data_snapshot
                (snapshot_id, source, as_of_date, fetched_at, content_hash,
                 status, records_json, report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.snapshot_id,
                snapshot.source,
                snapshot.as_of_date,
                snapshot.fetched_at,
                snapshot.content_hash,
                report.status,
                json.dumps(snapshot.records_by_code, ensure_ascii=False, sort_keys=True),
                json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True),
            ),
        )
        self.db.commit()
        return snapshot.snapshot_id

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM market_data_snapshot WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["records_by_code"] = json.loads(result.pop("records_json"))
        result["report"] = json.loads(result.pop("report_json"))
        return result
