"""执行一次确定性的自主候选评分、发布或回滚决策。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.versioned_strategy import default_strategy_config, load_active_strategy_config
from service.autopilot_service import AutopilotService, StrategyVersionStore, write_autopilot_report


def _git_revision() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _load_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("autopilot input must be a JSON object")
    return payload


def _metrics_from_payload(payload: dict) -> dict:
    """兼容候选指标 JSON 与正式回测 report-data.json。"""
    if isinstance(payload.get("metrics"), dict):
        return dict(payload["metrics"])
    result = payload.get("result")
    if not isinstance(result, dict):
        return dict(payload)
    manifest = payload.get("manifest") or {}
    data_quality = manifest.get("data_quality") or {}
    passed = payload.get("status") == "passed" and data_quality.get("status", "passed") == "passed"
    excess_return = float(result.get("excess_return", 0.0) or 0.0)
    return {
        "data_quality_passed": passed,
        "future_safe": payload.get("future_safe", manifest.get("future_safe", True)),
        "oos_12_excess_return": excess_return,
        "oos_24_excess_return": excess_return,
        "oos_sharpe": float(result.get("sharpe_ratio", 0.0) or 0.0),
        "max_drawdown": float(result.get("max_drawdown", 0.0) or 0.0),
        "annual_turnover": float(result.get("turnover_annual_pct", 0.0) or 0.0),
        "oos_stability": 1.0 if excess_return >= 0 else 0.0,
        "annual_return": float(result.get("annual_return", 0.0) or 0.0),
        "stress_passed": passed,
        "final_holdout_passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一次 Codex 自主优化发布决策")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--version-root", type=Path, default=Path("config/strategy_versions"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/autopilot"))
    parser.add_argument("--branch", default="codex/autopilot/local-run")
    parser.add_argument("--commit", default=None)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--max-backtests", type=int, default=100)
    parser.add_argument("--max-runtime-seconds", type=float, default=1800.0)
    parser.add_argument("--rollback-metrics", type=Path)
    parser.add_argument("--prior-windows", type=Path)
    args = parser.parse_args()

    candidate_payload = _load_payload(args.candidates)
    candidates = candidate_payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    store = StrategyVersionStore(args.version_root)
    active = load_active_strategy_config(args.version_root)
    store.initialize(active.get("config", default_strategy_config()), commit=active.get("commit", "baseline"))
    if args.baseline:
        baseline_metrics = _metrics_from_payload(_load_payload(args.baseline))
    else:
        baseline_metrics = candidate_payload.get("baseline_metrics") or active.get("evaluation", {}).get("metrics", {})
    if not baseline_metrics:
        raise ValueError("baseline metrics are required for autonomous scoring")

    service = AutopilotService(
        store,
        max_iterations=args.max_iterations,
        max_backtests=args.max_backtests,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    if args.rollback_metrics:
        observed_metrics = _metrics_from_payload(_load_payload(args.rollback_metrics))
        prior_windows = []
        if args.prior_windows:
            prior_windows = _load_payload(args.prior_windows).get("windows", [])
        rollback = service.rollback_if_needed(
            observed_metrics,
            baseline_metrics,
            prior_windows=prior_windows,
        )
        if rollback["status"] != "kept_current":
            decision = rollback
        else:
            decision = service.evaluate_and_publish(
                candidates,
                baseline_metrics=baseline_metrics,
                commit=args.commit or _git_revision(),
                branch=args.branch,
            )
    else:
        decision = service.evaluate_and_publish(
            candidates,
            baseline_metrics=baseline_metrics,
            commit=args.commit or _git_revision(),
            branch=args.branch,
        )
    decision["created_at"] = datetime.now(timezone.utc).isoformat()
    decision["run_id"] = f"autopilot-{uuid4().hex[:12]}"
    paths = write_autopilot_report(args.report_root, decision, decision["run_id"])
    print(json.dumps({"decision": decision, "report_paths": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
