"""Codex 自主优化的确定性评分、版本发布和回滚服务。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable
from uuid import uuid4


SCORE_WEIGHTS = {
    "oos_stability": 0.30,
    "sharpe": 0.25,
    "annual_return": 0.20,
    "drawdown": 0.15,
    "turnover_cost": 0.10,
}


def configuration_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _normalized_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    max_drawdown = abs(_finite_or_zero(metrics.get("max_drawdown", 0.0)))
    annual_turnover = max(0.0, _finite_or_zero(metrics.get("annual_turnover", 0.0)))
    return {
        "oos_stability": _clamp(_finite_or_zero(metrics.get("oos_stability", 0.0))),
        "sharpe": _clamp((_finite_or_zero(metrics.get("oos_sharpe", 0.0)) - 0.3) / 1.2),
        "annual_return": _clamp((_finite_or_zero(metrics.get("annual_return", 0.0)) + 10.0) / 40.0),
        "drawdown": _clamp(1.0 - max_drawdown / 35.0),
        "turnover_cost": _clamp(1.0 - annual_turnover / 360.0),
    }


def _score(metrics: dict[str, Any]) -> float:
    normalized = _normalized_metrics(metrics)
    return round(sum(SCORE_WEIGHTS[key] * normalized[key] for key in SCORE_WEIGHTS) * 100.0, 6)


_REQUIRED_METRIC_FIELDS = {
    "data_quality_passed",
    "future_safe",
    "oos_12_excess_return",
    "oos_24_excess_return",
    "oos_sharpe",
    "max_drawdown",
    "annual_turnover",
    "oos_stability",
    "annual_return",
    "stress_passed",
}


def _metric_number(metrics: dict[str, Any], name: str) -> float | None:
    try:
        value = float(metrics[name])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class CandidateEvaluation:
    config: dict[str, Any]
    config_hash: str
    metrics: dict[str, Any]
    score: float
    baseline_score: float
    score_improvement_pct: float
    accepted: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_candidate(
    config: dict[str, Any],
    metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> CandidateEvaluation:
    if not isinstance(config, dict):
        raise TypeError("candidate config must be an object")
    if not isinstance(metrics, dict) or not isinstance(baseline_metrics, dict):
        raise TypeError("candidate and baseline metrics must be objects")
    baseline_missing = sorted(_REQUIRED_METRIC_FIELDS - baseline_metrics.keys())
    baseline_invalid = sorted(
        name for name in _REQUIRED_METRIC_FIELDS
        if name not in {"data_quality_passed", "future_safe", "stress_passed"}
        and _metric_number(baseline_metrics, name) is None
    )
    if baseline_missing or baseline_invalid:
        raise ValueError("baseline metrics are incomplete or invalid")
    candidate_score = _score(metrics)
    baseline_score = _score(baseline_metrics)
    score_improvement_pct = (candidate_score - baseline_score) / max(abs(baseline_score), 1.0) * 100.0
    reasons: list[str] = []
    missing_fields = sorted(_REQUIRED_METRIC_FIELDS - metrics.keys())
    invalid_fields = sorted(
        name for name in _REQUIRED_METRIC_FIELDS
        if name not in {"data_quality_passed", "future_safe", "stress_passed"}
        and _metric_number(metrics, name) is None
    )
    if missing_fields:
        reasons.append("missing_metrics")
    if invalid_fields:
        reasons.append("invalid_metrics")
    if metrics.get("data_quality_passed") is not True:
        reasons.append("data_quality")
    if metrics.get("future_safe") is not True:
        reasons.append("future_function")
    if float(metrics.get("oos_12_excess_return", 0.0) or 0.0) < 0:
        reasons.append("oos_12_excess_return")
    if float(metrics.get("oos_24_excess_return", 0.0) or 0.0) < 0:
        reasons.append("oos_24_excess_return")
    if float(metrics.get("oos_sharpe", 0.0) or 0.0) < 0.3:
        reasons.append("oos_sharpe")
    if abs(float(metrics.get("max_drawdown", 0.0) or 0.0)) > 35.0:
        reasons.append("max_drawdown")
    if float(metrics.get("annual_turnover", 0.0) or 0.0) > 360.0:
        reasons.append("annual_turnover")
    if metrics.get("stress_passed") is not True:
        reasons.append("stress_test")
    if "final_holdout_passed" in metrics and metrics["final_holdout_passed"] is not True:
        reasons.append("final_holdout")
    baseline_drawdown = abs(float(baseline_metrics.get("max_drawdown", 0.0) or 0.0))
    candidate_drawdown = abs(float(metrics.get("max_drawdown", 0.0) or 0.0))
    if candidate_drawdown - baseline_drawdown > 3.0:
        reasons.append("drawdown_regression")
    if score_improvement_pct < 5.0:
        reasons.append("insufficient_improvement")
    return CandidateEvaluation(
        config=config,
        config_hash=configuration_hash(config),
        metrics=dict(metrics),
        score=candidate_score,
        baseline_score=baseline_score,
        score_improvement_pct=score_improvement_pct,
        accepted=not reasons,
        reasons=tuple(reasons),
    )


class StrategyVersionStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.active_path = self.root / "active-config.json"
        self.history_path = self.root / "release-history.json"
        self.lock_path = self.root / "rollback-locks.json"
        self.window_path = self.root / "evaluation-windows.json"

    def initialize(self, config: dict[str, Any], commit: str = "unknown") -> dict[str, Any]:
        if self.active_path.exists():
            active = self.load_active()
            expected_hash = configuration_hash(active["config"])
            if active.get("config_hash") and active["config_hash"] != expected_hash:
                raise ValueError("active strategy config hash does not match config")
            if not active.get("config_hash"):
                active["config_hash"] = expected_hash
                self._write_json(self.active_path, active)
            version_path = self.root / f"{active['version_id']}.json"
            if not version_path.exists():
                self._write_json(version_path, active)
            if not self.history_path.exists():
                self._write_json(self.history_path, [])
            if not self.lock_path.exists():
                self._write_json(self.lock_path, [])
            if not self.window_path.exists():
                self._write_json(self.window_path, [])
            return active
        self.root.mkdir(parents=True, exist_ok=True)
        payload = self._version_payload("baseline", config, configuration_hash(config), commit, None, {})
        self._write_json(self.root / "baseline.json", payload)
        self._write_json(self.active_path, payload)
        self._write_json(self.history_path, [])
        self._write_json(self.lock_path, [])
        self._write_json(self.window_path, [])
        return payload

    def load_active(self) -> dict[str, Any]:
        if not self.active_path.exists():
            raise FileNotFoundError(f"active strategy config not found: {self.active_path}")
        payload = json.loads(self.active_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
            raise ValueError(f"invalid active strategy config: {self.active_path}")
        if not payload.get("version_id"):
            raise ValueError(f"active strategy config has no version_id: {self.active_path}")
        return payload

    def is_hash_published(self, config_hash: str) -> bool:
        return any(
            item.get("event") == "publish" and item.get("config_hash") == config_hash
            for item in self._read_json(self.history_path, [])
        )

    def is_hash_locked(self, config_hash: str) -> bool:
        return config_hash in self._read_json(self.lock_path, [])

    def publish(
        self,
        config: dict[str, Any],
        evaluation: dict[str, Any],
        commit: str,
        branch: str,
    ) -> dict[str, Any]:
        config_hash = configuration_hash(config)
        if self.is_hash_locked(config_hash):
            raise ValueError(f"rollback-locked config: {config_hash}")
        if self.is_hash_published(config_hash):
            raise ValueError(f"duplicate config: {config_hash}")
        active = self.load_active()
        version_id = f"v-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{config_hash[:12]}"
        payload = self._version_payload(
            version_id, config, config_hash, commit, active["version_id"], evaluation
        )
        self._write_json(self.root / f"{version_id}.json", payload)
        self._write_json(self.active_path, payload)
        self._append_history({
            "event": "publish",
            "version_id": version_id,
            "config_hash": config_hash,
            "previous_version_id": active["version_id"],
            "commit": commit,
            "branch": branch,
            "evaluation": evaluation,
            "created_at": payload["created_at"],
        })
        return payload

    def rollback(self, reason: str) -> dict[str, Any]:
        active = self.load_active()
        previous_version_id = active.get("previous_version_id")
        if not previous_version_id:
            raise ValueError("no previous strategy version available")
        previous = json.loads((self.root / f"{previous_version_id}.json").read_text(encoding="utf-8"))
        locks = set(self._read_json(self.lock_path, []))
        locks.add(active["config_hash"])
        self._write_json(self.lock_path, sorted(locks))
        self._write_json(self.active_path, previous)
        self._append_history({
            "event": "rollback",
            "from_version_id": active["version_id"],
            "to_version_id": previous["version_id"],
            "config_hash": active["config_hash"],
            "reason": reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return previous

    def record_evaluation_window(self, metrics: dict[str, Any]) -> None:
        windows = self._read_json(self.window_path, [])
        windows.append({
            "metrics": metrics,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write_json(self.window_path, windows[-12:])

    def load_evaluation_windows(self) -> list[dict[str, Any]]:
        return [
            item.get("metrics", item)
            for item in self._read_json(self.window_path, [])
            if isinstance(item, dict)
        ]

    def _version_payload(
        self,
        version_id: str,
        config: dict[str, Any],
        config_hash: str,
        commit: str,
        previous_version_id: str | None,
        evaluation: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "version_id": version_id,
            "config": config,
            "config_hash": config_hash,
            "commit": commit,
            "previous_version_id": previous_version_id,
            "evaluation": evaluation,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _append_history(self, item: dict[str, Any]) -> None:
        history = self._read_json(self.history_path, [])
        history.append(item)
        self._write_json(self.history_path, history)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(path)


class AutopilotService:
    def __init__(
        self,
        version_store: StrategyVersionStore,
        max_iterations: int = 20,
        stagnation_limit: int = 3,
        max_backtests: int = 100,
        max_runtime_seconds: float = 1800.0,
    ):
        if max_iterations <= 0 or stagnation_limit <= 0 or max_backtests <= 0 or max_runtime_seconds <= 0:
            raise ValueError("autopilot budgets must be positive")
        self.version_store = version_store
        self.max_iterations = max_iterations
        self.stagnation_limit = stagnation_limit
        self.max_backtests = max_backtests
        self.max_runtime_seconds = max_runtime_seconds

    def evaluate_and_publish(
        self,
        candidates: Iterable[dict[str, Any]],
        baseline_metrics: dict[str, Any],
        commit: str,
        branch: str,
    ) -> dict[str, Any]:
        evaluations: list[CandidateEvaluation] = []
        best_score = float("-inf")
        started_at = time.monotonic()
        stop_reason = "input_exhausted"
        for index, candidate in enumerate(candidates):
            if index >= min(self.max_iterations, self.max_backtests):
                stop_reason = "budget_backtests"
                break
            if time.monotonic() - started_at >= self.max_runtime_seconds:
                stop_reason = "budget_runtime"
                break
            evaluation = score_candidate(candidate["config"], candidate["metrics"], baseline_metrics)
            if self.version_store.is_hash_locked(evaluation.config_hash):
                evaluation = CandidateEvaluation(
                    **{
                        **evaluation.to_dict(),
                        "accepted": False,
                        "reasons": tuple((*evaluation.reasons, "rollback_locked")),
                    }
                )
            evaluations.append(evaluation)
            if evaluation.score > best_score:
                best_score = evaluation.score
        accepted = [item for item in evaluations if item.accepted]
        accepted.sort(key=lambda item: item.score, reverse=True)
        if not accepted:
            return {
                "status": "kept_current",
                "published": None,
                "evaluations": [item.to_dict() for item in evaluations],
                "reason": "no_candidate_passed_hard_gates",
                "budget": {
                    "stop_reason": stop_reason,
                    "evaluated_candidates": len(evaluations),
                    "max_candidates": min(self.max_iterations, self.max_backtests),
                },
            }
        selected = accepted[0]
        published = self.version_store.publish(
            selected.config,
            selected.to_dict(),
            commit=commit,
            branch=branch,
        )
        return {
            "status": "published",
            "published": published,
            "evaluations": [item.to_dict() for item in evaluations],
            "reason": "best_candidate_passed_all_gates",
            "budget": {
                "stop_reason": stop_reason,
                "evaluated_candidates": len(evaluations),
                "max_candidates": min(self.max_iterations, self.max_backtests),
            },
        }

    def rollback_if_needed(
        self,
        observed_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
        prior_windows: Iterable[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """按硬风险和连续绩效恶化规则执行自动回滚。"""
        reasons: list[str] = []
        if observed_metrics.get("data_quality_passed") is not True:
            reasons.append("data_quality")
        if observed_metrics.get("future_safe") is not True:
            reasons.append("future_function")
        if observed_metrics.get("code_error") is True:
            reasons.append("code_error")
        if abs(_finite_or_zero(observed_metrics.get("max_drawdown"))) > 35.0:
            reasons.append("max_drawdown")

        baseline_score = _score(baseline_metrics)
        windows = self.version_store.load_evaluation_windows()
        windows.extend(prior_windows)
        windows.append(observed_metrics)
        if len(windows) >= 3 and all(
            _score(window) < baseline_score for window in windows[-3:]
        ):
            reasons.append("three_degraded_windows")

        if not reasons:
            self.version_store.record_evaluation_window(observed_metrics)
            return {"status": "kept_current", "rolled_back": None, "reasons": []}
        try:
            previous = self.version_store.rollback(",".join(reasons))
        except ValueError as error:
            self.version_store.record_evaluation_window(observed_metrics)
            return {
                "status": "rollback_unavailable",
                "rolled_back": None,
                "reasons": reasons,
                "error": str(error),
            }
        self.version_store.record_evaluation_window(observed_metrics)
        return {
            "status": "rolled_back",
            "rolled_back": previous,
            "reasons": reasons,
        }


def write_autopilot_report(root: str | Path, decision: dict[str, Any], run_id: str) -> dict[str, Path]:
    output = Path(root) / run_id
    output.mkdir(parents=True, exist_ok=True)
    normalized = json.loads(json.dumps(decision, ensure_ascii=False, default=str))
    data_path = output / "autopilot-manifest.json"
    markdown_path = output / "decision.md"
    html_path = output / "decision.html"
    comparison_path = output / "candidate-comparison.json"
    data_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_path.write_text(
        json.dumps(normalized.get("evaluations", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join([
            "# Codex 自主优化决策报告",
            "",
            f"- 运行 ID：`{run_id}`",
            f"- 状态：`{normalized.get('status', 'unknown')}`",
            f"- 原因：{normalized.get('reason', '')}",
            "",
            "## 决策事实",
            "",
            json.dumps(normalized, ensure_ascii=False, indent=2),
        ]),
        encoding="utf-8",
    )
    html_path.write_text(
        "<html><head><meta charset='utf-8'><title>Codex 自主优化决策报告</title></head>"
        "<body><h1>Codex 自主优化决策报告</h1><pre>"
        + html.escape(json.dumps(normalized, ensure_ascii=False, indent=2))
        + "</pre></body></html>",
        encoding="utf-8",
    )
    result = {"data": data_path, "comparison": comparison_path, "markdown": markdown_path, "html": html_path}
    if normalized.get("status") == "published":
        release_path = output / "release.json"
        release_path.write_text(json.dumps(normalized.get("published", {}), ensure_ascii=False, indent=2), encoding="utf-8")
        result["release"] = release_path
    if normalized.get("status") == "rolled_back":
        rollback_path = output / "rollback.json"
        rollback_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        result["rollback"] = rollback_path
    return result
