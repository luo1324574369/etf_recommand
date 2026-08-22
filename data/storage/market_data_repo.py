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
        return self._decode_row(row)

    def find_exact_passed_snapshot(
        self,
        source: str,
        codes: list[str],
        start_date: str,
        end_date: str,
    ) -> dict | None:
        rows = self.db.execute(
            """
            SELECT * FROM market_data_snapshot
            WHERE source = ? AND status = 'passed'
            ORDER BY fetched_at DESC
            """,
            (source,),
        ).fetchall()
        required_codes = set(codes)
        for row in rows:
            decoded = self._decode_row(row)
            metadata = decoded["report"].get("snapshot_metadata", {})
            if metadata.get("start_date") != start_date or metadata.get("end_date") != end_date:
                continue
            if not required_codes.issubset(decoded["records_by_code"]):
                continue
            return decoded
        return None

    def latest_passed_snapshot_metadata(self, source: str) -> dict | None:
        snapshots = self.list_passed_snapshot_metadata(source)
        return snapshots[0] if snapshots else None

    def list_passed_snapshot_metadata(self, source: str) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT snapshot_id, source, as_of_date, fetched_at, report_json
            FROM market_data_snapshot
            WHERE source = ? AND status = 'passed'
            ORDER BY fetched_at DESC
            """,
            (source,),
        ).fetchall()
        snapshots = []
        for row in rows:
            report = json.loads(row["report_json"])
            snapshots.append({
                "snapshot_id": row["snapshot_id"],
                "source": row["source"],
                "as_of_date": row["as_of_date"],
                "fetched_at": row["fetched_at"],
                "snapshot_metadata": report.get("snapshot_metadata", {}),
            })
        return snapshots

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["records_by_code"] = json.loads(result.pop("records_json"))
        result["report"] = json.loads(result.pop("report_json"))
        return result
