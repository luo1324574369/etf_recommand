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

    @classmethod
    def from_records(
        cls,
        records_by_code: dict[str, list[dict[str, Any]]],
        source: str,
        as_of_date: str,
        fetched_at: str | None = None,
    ) -> "MarketDataSnapshot":
        canonical = _canonical_records(records_by_code)
        payload = {
            "as_of_date": as_of_date,
            "records": canonical,
            "source": source,
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
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "as_of_date": self.as_of_date,
            "fetched_at": self.fetched_at,
            "records_by_code": self.records_by_code,
            "content_hash": self.content_hash,
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

    @classmethod
    def passed(cls, snapshot_id: str) -> "DataQualityReport":
        return cls(snapshot_id=snapshot_id, status="passed")

    @classmethod
    def blocked(
        cls,
        snapshot_id: str,
        issues: list[ValidationIssue] | tuple[ValidationIssue, ...],
    ) -> "DataQualityReport":
        return cls(snapshot_id=snapshot_id, status="blocked", issues=tuple(issues))

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_at": self.checked_at,
        }
