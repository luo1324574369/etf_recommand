"""Codex 自主优化的确定性评分、版本发布和回滚服务。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from collections import Counter
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
    annual_cost = max(0.0, _finite_or_zero(metrics.get("annual_cost_pct", 0.0)))
    turnover_and_cost = 0.7 * annual_turnover / 360.0 + 0.3 * annual_cost / 5.0
    return {
        "oos_stability": _clamp(_finite_or_zero(metrics.get("oos_stability", 0.0))),
        "sharpe": _clamp((_finite_or_zero(metrics.get("oos_sharpe", 0.0)) - 0.3) / 1.2),
        "annual_return": _clamp((_finite_or_zero(metrics.get("annual_return", 0.0)) + 10.0) / 40.0),
        "drawdown": _clamp(1.0 - max_drawdown / 35.0),
        "turnover_cost": _clamp(1.0 - turnover_and_cost),
    }


def _score(metrics: dict[str, Any]) -> float:
    normalized = _normalized_metrics(metrics)
    return round(sum(SCORE_WEIGHTS[key] * normalized[key] for key in SCORE_WEIGHTS) * 100.0, 6)


def _selection_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """返回只包含候选选择期事实的指标视图。"""
    selection = metrics.get("selection_metrics")
    if isinstance(selection, dict):
        return dict(selection)
    return dict(metrics)


def _final_holdout_reasons(metrics: dict[str, Any]) -> tuple[str, ...]:
    """检查候选被选中后才允许读取的最终留出集。"""
    holdout = metrics.get("final_holdout_metrics")
    if not isinstance(holdout, dict):
        if isinstance(metrics.get("selection_metrics"), dict):
            return ("final_holdout_unavailable",)
        holdout = metrics

    reasons = []
    if holdout.get("available") is False:
        reasons.append("final_holdout_unavailable")
    excess_return = holdout.get("oos_12_excess_return", holdout.get("excess_return"))
    sharpe = holdout.get("oos_sharpe", holdout.get("sharpe_ratio"))
    max_drawdown = holdout.get("max_drawdown")
    for value in (excess_return, sharpe, max_drawdown):
        try:
            if not math.isfinite(float(value)):
                reasons.append("final_holdout_invalid")
        except (TypeError, ValueError):
            reasons.append("final_holdout_invalid")
    if _finite_or_zero(excess_return) < 0:
        reasons.append("final_holdout_excess_return")
    if _finite_or_zero(sharpe) < 0.3:
        reasons.append("final_holdout_sharpe")
    if abs(_finite_or_zero(max_drawdown)) > 35.0:
        reasons.append("final_holdout_max_drawdown")
    return tuple(dict.fromkeys(reasons))


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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_candidate(
    config: dict[str, Any],
    metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    selection_only: bool = False,
) -> CandidateEvaluation:
    if not isinstance(config, dict):
        raise TypeError("candidate config must be an object")
    if not isinstance(metrics, dict) or not isinstance(baseline_metrics, dict):
        raise TypeError("candidate and baseline metrics must be objects")
    candidate_selection_metrics = _selection_metrics(metrics) if selection_only else dict(metrics)
    baseline_selection_metrics = _selection_metrics(baseline_metrics) if selection_only else dict(baseline_metrics)
    baseline_missing = sorted(_REQUIRED_METRIC_FIELDS - baseline_selection_metrics.keys())
    baseline_invalid = sorted(
        name for name in _REQUIRED_METRIC_FIELDS
        if name not in {"data_quality_passed", "future_safe", "stress_passed"}
        and _metric_number(baseline_selection_metrics, name) is None
    )
    if baseline_missing or baseline_invalid:
        raise ValueError("baseline metrics are incomplete or invalid")
    candidate_score = _score(candidate_selection_metrics)
    baseline_score = _score(baseline_selection_metrics)
    score_improvement_pct = (candidate_score - baseline_score) / max(abs(baseline_score), 1.0) * 100.0
    reasons: list[str] = []
    missing_fields = sorted(_REQUIRED_METRIC_FIELDS - candidate_selection_metrics.keys())
    invalid_fields = sorted(
        name for name in _REQUIRED_METRIC_FIELDS
        if name not in {"data_quality_passed", "future_safe", "stress_passed"}
        and _metric_number(candidate_selection_metrics, name) is None
    )
    if missing_fields:
        reasons.append("missing_metrics")
    if invalid_fields:
        reasons.append("invalid_metrics")
    if candidate_selection_metrics.get("data_quality_passed") is not True:
        reasons.append("data_quality")
    if candidate_selection_metrics.get("future_safe") is not True:
        reasons.append("future_function")
    if not selection_only and _finite_or_zero(candidate_selection_metrics.get("oos_12_excess_return", 0.0)) < 0:
        reasons.append("oos_12_excess_return")
    if _finite_or_zero(candidate_selection_metrics.get("oos_24_excess_return", 0.0)) < 0:
        reasons.append("oos_24_excess_return")
    if _finite_or_zero(candidate_selection_metrics.get("oos_sharpe", 0.0)) < 0.3:
        reasons.append("oos_sharpe")
    if abs(_finite_or_zero(candidate_selection_metrics.get("max_drawdown", 0.0))) > 35.0:
        reasons.append("max_drawdown")
    if _finite_or_zero(candidate_selection_metrics.get("annual_turnover", 0.0)) > 360.0:
        reasons.append("annual_turnover")
    if candidate_selection_metrics.get("stress_passed") is not True:
        reasons.append("stress_test")
    if not selection_only and "final_holdout_passed" in metrics and metrics["final_holdout_passed"] is not True:
        reasons.append("final_holdout")
    baseline_drawdown = abs(_finite_or_zero(baseline_selection_metrics.get("max_drawdown", 0.0)))
    candidate_drawdown = abs(_finite_or_zero(candidate_selection_metrics.get("max_drawdown", 0.0)))
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
        metadata=dict(metadata or {}),
    )


def _configuration_scope_reasons(config: dict[str, Any], active_config: dict[str, Any]) -> tuple[str, ...]:
    if set(config) - {"params", "factor_weights", "constraints"}:
        return ("out_of_scope_config",)
    candidate_params = config.get("params", {})
    active_params = active_config.get("params", {})
    if not isinstance(candidate_params, dict) or not isinstance(active_params, dict):
        return ("out_of_scope_config",)
    if set(candidate_params) - set(active_params) - {"factor_weights", "constraints", "force_factor_weights"}:
        return ("out_of_scope_config",)
    if config.get("constraints", {}) != active_config.get("constraints", {}):
        return ("risk_constraints_are_not_auto_optimizable",)
    return ()


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
        selection_only: bool = False,
    ) -> dict[str, Any]:
        evaluations: list[CandidateEvaluation] = []
        best_score = float("-inf")
        started_at = time.monotonic()
        stop_reason = "input_exhausted"
        active_config = self.version_store.load_active().get("config", {})
        for index, candidate in enumerate(candidates):
            if index >= min(self.max_iterations, self.max_backtests):
                stop_reason = "budget_backtests"
                break
            if time.monotonic() - started_at >= self.max_runtime_seconds:
                stop_reason = "budget_runtime"
                break
            metadata = {
                key: candidate[key]
                for key in ("optimization_stage", "search_round", "search_profile")
                if key in candidate
            }
            evaluation = score_candidate(
                candidate["config"],
                candidate["metrics"],
                baseline_metrics,
                metadata=metadata,
                selection_only=selection_only,
            )
            scope_reasons = _configuration_scope_reasons(candidate["config"], active_config)
            if scope_reasons:
                evaluation = replace(
                    evaluation,
                    accepted=False,
                    reasons=tuple((*evaluation.reasons, *scope_reasons)),
                )
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
                    "selection_method": "evaluate_all_within_budget_then_rank_accepted",
                },
                "selection": {
                    "method": "hard_gates_then_score_desc",
                    "evaluated": len(evaluations),
                    "accepted": 0,
                    "selected": None,
                },
            }
        selected = accepted[0]
        if selection_only:
            final_reasons = _final_holdout_reasons(selected.metrics)
            if final_reasons:
                selected = replace(
                    selected,
                    accepted=False,
                    reasons=tuple((*selected.reasons, *final_reasons)),
                )
                for index, evaluation in enumerate(evaluations):
                    if evaluation.config_hash == selected.config_hash:
                        evaluations[index] = selected
                        break
                return {
                    "status": "kept_current",
                    "published": None,
                    "evaluations": [item.to_dict() for item in evaluations],
                    "reason": "selected_candidate_failed_final_holdout",
                    "budget": {
                        "stop_reason": stop_reason,
                        "evaluated_candidates": len(evaluations),
                        "max_candidates": min(self.max_iterations, self.max_backtests),
                        "selection_method": "selection_oos_rank_then_single_final_holdout",
                    },
                    "selection": {
                        "method": "24_month_oos_hard_gates_then_single_final_holdout",
                        "evaluated": len(evaluations),
                        "accepted": 0,
                        "selected": selected.metadata,
                    },
                }
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
                "selection_method": "evaluate_all_within_budget_then_rank_accepted",
            },
            "selection": {
                "method": "hard_gates_then_score_desc",
                "evaluated": len(evaluations),
                "accepted": len(accepted),
                "selected": selected.metadata,
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


def write_autopilot_report(
    root: str | Path,
    decision: dict[str, Any],
    run_id: str,
    operation_log: list[dict[str, Any]] | None = None,
    next_plan: dict[str, Any] | None = None,
) -> dict[str, Path]:
    output = Path(root) / run_id
    output.mkdir(parents=True, exist_ok=True)
    from service.reporting import _json_payload

    normalized = _json_payload(decision)
    normalized["operation_log"] = _json_payload(
        operation_log if operation_log is not None else normalized.get("operation_log", [])
    )
    normalized["next_plan"] = _json_payload(
        next_plan if next_plan is not None else normalized.get("next_plan", {})
    )
    data_path = output / "autopilot-manifest.json"
    markdown_path = output / "decision.md"
    html_path = output / "decision.html"
    comparison_path = output / "candidate-comparison.json"
    operation_log_path = output / "operation-log.jsonl"
    next_plan_path = output / "next-plan.json"
    data_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison_path.write_text(
        json.dumps(normalized.get("evaluations", []), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    operation_log_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in normalized["operation_log"]),
        encoding="utf-8",
    )
    next_plan_path.write_text(
        json.dumps(normalized["next_plan"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    candidate_dir = output / "candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for index, evaluation in enumerate(normalized.get("evaluations", []), start=1):
        (candidate_dir / f"candidate-{index:03d}.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    next_plan_payload = normalized.get("next_plan", {})
    expected_goal = next_plan_payload.get("expected_optimization_goal", {})
    if isinstance(expected_goal, dict):
        goal_text = (
            f"{expected_goal.get('focus', '未定义')}；"
            f"当前：{expected_goal.get('current', '未知')}；"
            f"目标：{expected_goal.get('target', '未知')}"
        )
    else:
        goal_text = str(expected_goal or "未定义")
    operations = []
    data_ranges = []
    for operation in normalized.get("operation_log", []):
        operation_name = operation.get("operation")
        if operation_name and operation_name not in operations:
            operations.append(operation_name)
        if operation.get("data_range") and operation.get("data_range") not in data_ranges:
            data_ranges.append(operation["data_range"])
    evaluations = normalized.get("evaluations", [])
    rejection_reasons = Counter(
        reason
        for evaluation in evaluations
        for reason in evaluation.get("reasons", [])
    )
    attempt_groups: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        metadata = evaluation.get("metadata") or {}
        group_key = metadata.get("search_profile") or metadata.get("optimization_stage") or "未分类候选"
        group = attempt_groups.setdefault(
            group_key,
            {"count": 0, "accepted": 0, "best": None, "reasons": Counter()},
        )
        group["count"] += 1
        if evaluation.get("accepted") is True:
            group["accepted"] += 1
        group["reasons"].update(evaluation.get("reasons", []))
        if group["best"] is None or _finite_or_zero(evaluation.get("score")) > _finite_or_zero(group["best"].get("score")):
            group["best"] = evaluation
    status_labels = {
        "published": "已发布",
        "kept_current": "保持当前版本",
        "rolled_back": "已回滚",
        "blocked": "阻塞",
    }
    status = status_labels.get(normalized.get("status"), normalized.get("status", "未知"))
    summary_lines = [
        "# ETF 自主优化决策汇报",
        "",
        f"- 运行 ID：`{run_id}`",
        f"- 当前状态：{status}",
        f"- 本轮预期优化目标：{goal_text}",
        "",
        "## 本轮尝试",
        "",
        f"- 回测区间：{json.dumps(data_ranges, ensure_ascii=False, separators=(',', ':')) if data_ranges else '报告未提供'}",
        f"- 执行轮次：{len(evaluations)} 个候选；自动完成基线、候选、OOS、留出集和压力测试。",
        "- 选择规则：仅用24个月 OOS 排名和筛选；最高分候选再单独检查最近12个月最终留出集，留出集不参与候选间比较。",
    ]
    if operations:
        summary_lines.extend(f"- {operation}" for operation in operations)
    if attempt_groups:
        summary_lines.extend(["", "## 尝试与效果", ""])
        for group_key, group in attempt_groups.items():
            best = group["best"] or {}
            metrics = best.get("metrics") or {}
            reasons = "、".join(
                f"{reason}（{count}）" for reason, count in group["reasons"].most_common(3)
            ) or "无淘汰原因"
            summary_lines.append(
                f"- {group_key}：尝试 {group['count']} 个，{group['accepted']} 个通过；"
                f"最佳评分 {_finite_or_zero(best.get('score')):.2f}，"
                f"相对基线 {_finite_or_zero(best.get('score_improvement_pct')):.2f}%；"
                f"12个月 OOS 超额 {_finite_or_zero(metrics.get('oos_12_excess_return')):.2f}%，"
                f"24个月 {_finite_or_zero(metrics.get('oos_24_excess_return')):.2f}%，"
                f"Sharpe {_finite_or_zero(metrics.get('oos_sharpe')):.2f}；"
                f"主要结果：{('已通过并可发布' if best.get('accepted') else reasons)}。"
            )
    summary_lines.extend([
        "",
        "## 结果",
        "",
        f"- {normalized.get('reason', '未记录决策原因')}",
    ])
    selection = normalized.get("selection") or {}
    if selection:
        summary_lines.append(
            f"- 择优：完成 {selection.get('evaluated', 0)} 个候选评估，"
            f"{selection.get('accepted', 0)} 个通过硬门槛，按风险调整综合评分选择最佳候选。"
        )
    published = normalized.get("published") or {}
    if published:
        summary_lines.append(
            f"- 发布版本：`{published.get('version_id', '未知')}`；配置哈希：`{published.get('config_hash', '未知')}`。"
        )
    if rejection_reasons:
        reason_text = "、".join(
            f"{reason}（{count}）" for reason, count in rejection_reasons.most_common()
        )
        summary_lines.extend(["", "## 未达成原因", "", f"- 候选淘汰原因：{reason_text}。"])
    summary_lines.extend([
        "",
        "## 下一轮计划",
        "",
        f"- 优先动作：{next_plan_payload.get('current_action', '继续诊断')}。",
        f"- 预期改善：{goal_text}。",
        f"- 后续优化：{next_plan_payload.get('next_optimization', '继续运行互补参数候选并完整验证后择优')}。",
        f"- 执行方式：{next_plan_payload.get('next_run', '继续使用既定 OOS 和风险门槛验证')}。",
    ])
    if normalized.get("status") == "blocked":
        summary_lines.extend(["", "- 需要用户决策：是；原因：" + str(normalized.get("reason", "未记录"))])
    else:
        continuation = normalized.get("continuation") or {}
        stop_reason = (normalized.get("budget") or {}).get("stop_reason")
        stop_messages = {
            "budget_backtests": "本轮达到候选回测预算",
            "budget_runtime": "本轮达到运行时间预算",
        }
        if continuation.get("required"):
            continuation = "当前候选批次已完成，不是自主优化终止；Skill 必须自动开始下一轮，不得等待用户确认。"
        elif stop_reason in stop_messages:
            continuation = f"{stop_messages[stop_reason]}，本次自动结束；下次重新唤起 Skill 后继续。"
        elif stop_reason == "stagnation":
            continuation = "本轮搜索停滞，已自动结束；下次重新唤起 Skill 后继续。"
        else:
            continuation = "本轮候选已评估完成；如仍需继续搜索，下次重新唤起 Skill。"
        summary_lines.extend(["", f"- 需要用户决策：否；{continuation}"])
    markdown_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    html_path.write_text(
        "<html><head><meta charset='utf-8'><title>Codex 自主优化决策报告</title></head>"
        "<body><h1>Codex 自主优化决策报告</h1><pre>"
        + html.escape(json.dumps(normalized, ensure_ascii=False, indent=2))
        + "</pre></body></html>",
        encoding="utf-8",
    )
    result = {
        "data": data_path,
        "comparison": comparison_path,
        "operation_log": operation_log_path,
        "next_plan": next_plan_path,
        "candidates": candidate_dir,
        "markdown": markdown_path,
        "html": html_path,
    }
    if normalized.get("status") == "published":
        release_path = output / "release.json"
        release_path.write_text(json.dumps(normalized.get("published", {}), ensure_ascii=False, indent=2), encoding="utf-8")
        result["release"] = release_path
    if normalized.get("status") == "rolled_back":
        rollback_path = output / "rollback.json"
        rollback_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        result["rollback"] = rollback_path
    return result
