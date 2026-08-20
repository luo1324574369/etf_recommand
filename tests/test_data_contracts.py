import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_snapshot_hash_is_stable_and_report_serializes():
    from data.contracts import DataQualityReport, MarketDataSnapshot

    records = {"510300": [{"trade_date": "2025-01-02", "close": 4.0}]}
    snapshot = MarketDataSnapshot.from_records(
        records,
        source="tushare",
        as_of_date="2025-01-02",
        fetched_at="2025-01-02T16:00:00+08:00",
    )
    repeated_snapshot = MarketDataSnapshot.from_records(
        records,
        source="tushare",
        as_of_date="2025-01-02",
        fetched_at="2025-01-02T16:00:00+08:00",
    )

    report = DataQualityReport.passed(snapshot.snapshot_id)

    assert snapshot.content_hash == repeated_snapshot.content_hash
    assert report.to_dict()["status"] == "passed"
    assert report.to_dict()["snapshot_id"] == snapshot.snapshot_id
