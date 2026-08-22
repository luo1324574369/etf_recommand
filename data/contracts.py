"""可复现行情输入和数据质量报告的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal


def _canonical_records(records_by_code: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    canonical = {}
    for code in sorted(records_by_code):
        rows = records_by_code[code]
        canonical[code] = [
            {key: row[key] for key in sorted(row)}
            for row in sorted(rows, key=lambda item: str(item.get("trade_date", "")))
        ]
    return canonical


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketDataSnapshot:
    snapshot_id: str
    source: str
    as_of_date: str
    fetched_at: str
    records_by_code: dict[str, list[dict[str, Any]]]
    content_hash: str
    start_date: str | None = None
    end_date: str | None = None
    data_version: str = "unknown"
    record_count: int = 0
    observed_dates: tuple[str, ...] = field(default_factory=tuple)
    missing_dates: tuple[str, ...] = field(default_factory=tuple)
    duplicate_records: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_records(
        cls,
        records_by_code: dict[str, list[dict[str, Any]]],
        source: str,
        as_of_date: str,
        fetched_at: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        expected_dates: list[str] | tuple[str, ...] | None = None,
        data_version: str = "unknown",
    ) -> "MarketDataSnapshot":
        canonical = _canonical_records(records_by_code)
        observed_dates = sorted({
            str(row.get("trade_date"))
            for rows in canonical.values()
            for row in rows
            if row.get("trade_date")
        })
        expected_date_set = set(expected_dates or ())
        duplicate_records = sorted({
            f"{code}:{row.get('trade_date')}"
            for code, rows in canonical.items()
            for row in rows
            if row.get("trade_date") and sum(
                1 for candidate in rows if candidate.get("trade_date") == row.get("trade_date")
            ) > 1
        })
        payload = {
            "as_of_date": as_of_date,
            "records": canonical,
            "source": source,
            "start_date": start_date,
            "end_date": end_date,
            "expected_dates": sorted(expected_date_set),
            "data_version": data_version,
        }
        content_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            snapshot_id=f"{as_of_date}-{content_hash[:12]}",
            source=source,
            as_of_date=as_of_date,
            fetched_at=fetched_at or _now_iso(),
            records_by_code=canonical,
            content_hash=content_hash,
            start_date=start_date or (observed_dates[0] if observed_dates else None),
            end_date=end_date or (observed_dates[-1] if observed_dates else None),
            data_version=data_version,
            record_count=sum(len(rows) for rows in canonical.values()),
            observed_dates=tuple(observed_dates),
            missing_dates=tuple(sorted(expected_date_set - set(observed_dates))),
            duplicate_records=tuple(duplicate_records),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "as_of_date": self.as_of_date,
            "fetched_at": self.fetched_at,
            "records_by_code": self.records_by_code,
            "content_hash": self.content_hash,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "data_version": self.data_version,
            "record_count": self.record_count,
            "observed_dates": list(self.observed_dates),
            "missing_dates": list(self.missing_dates),
            "duplicate_records": list(self.duplicate_records),
        }


@dataclass(frozen=True)
class ValidationIssue:
    rule: str
    code: str | None
    message: str
    actual: Any = None
    expected: Any = None
    severity: Literal["error", "warning"] = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "code": self.code,
            "message": self.message,
            "actual": self.actual,
            "expected": self.expected,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class DataQualityReport:
    snapshot_id: str
    status: Literal["passed", "blocked"]
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    checked_at: str = field(default_factory=_now_iso)
    snapshot_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def passed(
        cls, snapshot_id: str, snapshot: MarketDataSnapshot | None = None
    ) -> "DataQualityReport":
        return cls(
            snapshot_id=snapshot_id,
            status="passed",
            snapshot_metadata=_snapshot_metadata(snapshot),
        )

    @classmethod
    def blocked(
        cls,
        snapshot_id: str,
        issues: list[ValidationIssue] | tuple[ValidationIssue, ...],
        snapshot: MarketDataSnapshot | None = None,
    ) -> "DataQualityReport":
        return cls(
            snapshot_id=snapshot_id,
            status="blocked",
            issues=tuple(issues),
            snapshot_metadata=_snapshot_metadata(snapshot),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DataQualityReport":
        issues = tuple(
            ValidationIssue(
                rule=item.get("rule", "unknown"),
                code=item.get("code"),
                message=item.get("message", ""),
                actual=item.get("actual"),
                expected=item.get("expected"),
                severity=item.get("severity", "error"),
            )
            for item in payload.get("issues", [])
        )
        return cls(
            snapshot_id=payload.get("snapshot_id", "unknown"),
            status=payload.get("status", "blocked"),
            issues=issues,
            checked_at=payload.get("checked_at", _now_iso()),
            snapshot_metadata=payload.get("snapshot_metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_at": self.checked_at,
            "snapshot_metadata": self.snapshot_metadata,
        }


def _snapshot_metadata(snapshot: MarketDataSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {}
    return {
        "source": snapshot.source,
        "start_date": snapshot.start_date,
        "end_date": snapshot.end_date,
        "data_version": snapshot.data_version,
        "record_count": snapshot.record_count,
        "observed_dates": list(snapshot.observed_dates),
        "missing_dates": list(snapshot.missing_dates),
        "duplicate_records": list(snapshot.duplicate_records),
        "content_hash": snapshot.content_hash,
    }
