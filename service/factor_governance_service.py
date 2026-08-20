"""因子候选的 OOS、审批、影子运行和季度发布流程。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import json
from pathlib import Path
from uuid import uuid4

from strategy.factor_registry import FactorDefinition, FactorRegistry


@dataclass(frozen=True)
class FactorCandidate:
    candidate_id: str
    definition: FactorDefinition
    score: float
    stage: str = "submitted"
    oos_12_passed: bool = False
    oos_24_passed: bool = False
    approved_by: str | None = None
    shadow_metrics: dict | None = None

    def to_dict(self) -> dict:
        value = asdict(self)
        value["definition"] = self.definition.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "FactorCandidate":
        return cls(
            candidate_id=value["candidate_id"],
            definition=FactorDefinition.from_dict(value["definition"]),
            score=float(value["score"]),
            stage=value.get("stage", "submitted"),
            oos_12_passed=bool(value.get("oos_12_passed", False)),
            oos_24_passed=bool(value.get("oos_24_passed", False)),
            approved_by=value.get("approved_by"),
            shadow_metrics=value.get("shadow_metrics"),
        )


class FactorGovernanceService:
    def __init__(self, path: str | Path, registry: FactorRegistry):
        self.path = Path(path)
        self.registry = registry
        self._candidates: dict[str, FactorCandidate] = {}
        self._load()

    def submit_candidate(self, definition: FactorDefinition, score: float) -> FactorCandidate:
        if score <= 0:
            raise ValueError("candidate score must be positive")
        self.registry.register(definition)
        candidate = FactorCandidate(
            candidate_id=f"candidate-{uuid4().hex[:12]}",
            definition=definition,
            score=score,
        )
        self._candidates[candidate.candidate_id] = candidate
        self._save()
        return candidate

    def get_candidate(self, candidate_id: str) -> FactorCandidate:
        try:
            return self._candidates[candidate_id]
        except KeyError as error:
            raise KeyError(f"candidate not found: {candidate_id}") from error

    def list_candidates(self) -> list[FactorCandidate]:
        return list(self._candidates.values())

    def record_oos(self, candidate_id: str, months: int, passed: bool) -> FactorCandidate:
        candidate = self.get_candidate(candidate_id)
        if months not in {12, 24}:
            raise ValueError("OOS window must be 12 or 24 months")
        if not passed:
            updated = replace(candidate, stage="rejected")
        elif months == 12:
            updated = replace(candidate, oos_12_passed=True, stage="screened")
        elif not candidate.oos_12_passed:
            raise ValueError("12-month OOS must pass before 24-month OOS")
        else:
            updated = replace(candidate, oos_24_passed=True, stage="confirmed")
        self._candidates[candidate_id] = updated
        self._save()
        return updated

    def approve_candidate(self, candidate_id: str, approver: str) -> FactorCandidate:
        candidate = self.get_candidate(candidate_id)
        if not candidate.oos_12_passed:
            raise ValueError("12-month OOS must pass before approval")
        if not candidate.oos_24_passed:
            raise ValueError("24-month OOS must pass before approval")
        self.registry.request_approval(candidate.definition.name, candidate.definition.version)
        updated = replace(candidate, stage="approved", approved_by=approver)
        self._candidates[candidate_id] = updated
        self._save()
        return updated

    def start_shadow_run(self, candidate_id: str, start_date: str, end_date: str) -> FactorCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate.stage != "approved":
            raise ValueError("candidate must be approved before shadow run")
        if date.fromisoformat(end_date) < date.fromisoformat(start_date):
            raise ValueError("shadow run end date must not precede start date")
        updated = replace(candidate, stage="shadow")
        self._candidates[candidate_id] = updated
        self._save()
        return updated

    def complete_shadow_run(self, candidate_id: str, metrics: dict) -> FactorCandidate:
        candidate = self.get_candidate(candidate_id)
        if candidate.stage != "shadow":
            raise ValueError("candidate must be in shadow run before completion")
        updated = replace(candidate, stage="publishable", shadow_metrics=dict(metrics))
        self._candidates[candidate_id] = updated
        self._save()
        return updated

    def publish_quarterly(self, candidate_id: str, publish_date: str) -> FactorDefinition:
        candidate = self.get_candidate(candidate_id)
        if candidate.stage != "publishable":
            raise ValueError("candidate must complete shadow run before publishing")
        if date.fromisoformat(publish_date).month not in {1, 4, 7, 10}:
            raise ValueError("factor publication is limited to quarterly windows")
        activated = self.registry.activate(
            candidate.definition.name,
            candidate.definition.version,
            approved_by=candidate.approved_by or "unknown",
        )
        self._candidates[candidate_id] = replace(candidate, stage="active")
        self._save()
        return activated

    def _load(self) -> None:
        if not self.path.exists():
            return
        values = json.loads(self.path.read_text(encoding="utf-8"))
        self._candidates = {
            value["candidate_id"]: FactorCandidate.from_dict(value)
            for value in values
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                [candidate.to_dict() for candidate in self._candidates.values()],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
