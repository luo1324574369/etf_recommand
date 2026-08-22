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

from config.settings import DB_PATH
from config.versioned_strategy import default_strategy_config, load_active_strategy_config
from service.autopilot_service import AutopilotService, StrategyVersionStore, write_autopilot_report
from service.autopilot_diagnostics import build_next_plan


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
        "annual_cost_pct": float(result.get("annual_cost_pct", 0.0) or 0.0),
        "oos_stability": 1.0 if excess_return >= 0 else 0.0,
        "annual_return": float(result.get("annual_return", 0.0) or 0.0),
        "stress_passed": passed,
        "final_holdout_passed": passed,
    }


def _create_git_release(branch, version_root, report_paths):
    subprocess.run(["git", "switch", "-c", branch], check=True)
    paths = [str(version_root)] + [str(path) for path in report_paths.values()]
    subprocess.run(["git", "add", "-f", *paths], check=True)
    subprocess.run(["git", "commit", "-m", f"chore: publish ETF strategy {branch}"], check=True)
    commit = _git_revision()
    subprocess.run(["git", "push", "-u", "origin", branch], check=True)
    return commit


def _continuation_payload(decision: dict) -> dict:
    """区分候选批次结束与自主优化终止，供 Skill 自动循环使用。"""
    stop_reason = (decision.get("budget") or {}).get("stop_reason")
    required = decision.get("status") != "blocked" and stop_reason == "input_exhausted"
    return {
        "required": required,
        "terminal": not required,
        "reason": "candidate_batch_complete" if required else (stop_reason or decision.get("status", "completed")),
        "next_action": "start_next_optimization_round" if required else "stop_and_report",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="运行一批候选并返回 Codex 自主优化是否继续下一轮")
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
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--codes", nargs="*", default=None)
    parser.add_argument(
        "--allow-unverified-input",
        action="store_true",
        help="仅用于离线单元测试；生产发布必须提供 --start 和 --end 重新验证",
    )
    parser.add_argument(
        "--git-release",
        action="store_true",
        help="发布成功后创建 codex 分支、提交版本证据并推送 origin",
    )
    args = parser.parse_args()
    if args.git_release and args.branch in {"main", "master"}:
        raise ValueError("自动发布禁止直接使用 main/master 分支")

    candidate_payload = _load_payload(args.candidates)
    if candidate_payload.get("status") == "blocked":
        decision = {
            "status": "blocked",
            "reason": candidate_payload.get("reason", "candidate_generation_blocked"),
            "data_quality": candidate_payload.get("data_quality", {}),
            "repair_attempt": candidate_payload.get("repair_attempt"),
            "evaluations": [],
            "operation_log": candidate_payload.get("operation_log", []),
            "next_plan": candidate_payload.get("next_plan", {}),
        }
        decision["created_at"] = datetime.now(timezone.utc).isoformat()
        decision["continuation"] = _continuation_payload(decision)
        decision["run_id"] = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/autopilot-{uuid4().hex[:12]}"
        paths = write_autopilot_report(
            args.report_root,
            decision,
            decision["run_id"],
            operation_log=decision["operation_log"],
            next_plan=decision["next_plan"],
        )
        print(json.dumps({"decision": decision, "report_paths": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))
        return 2
    if bool(args.start) != bool(args.end):
        raise ValueError("--start and --end must be provided together")
    if args.start and args.end:
        if args.baseline:
            raise ValueError("--baseline cannot override the revalidated baseline")
        from scripts.build_autopilot_candidates import revalidate_candidate_payload

        candidate_payload = revalidate_candidate_payload(
            candidate_payload,
            args.start,
            args.end,
            db_path=args.db,
            codes=args.codes,
            version_root=args.version_root,
        )
    elif not args.allow_unverified_input:
        raise ValueError("候选发布前必须提供 --start/--end 重新执行数据质量、OOS和压力测试")
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
    selection_only = bool(args.start and args.end)
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
                selection_only=selection_only,
            )
    else:
        decision = service.evaluate_and_publish(
            candidates,
            baseline_metrics=baseline_metrics,
            commit=args.commit or _git_revision(),
            branch=args.branch,
            selection_only=selection_only,
        )
    decision["created_at"] = datetime.now(timezone.utc).isoformat()
    decision["diagnostics"] = candidate_payload.get("diagnostics", {})
    decision["operation_log"] = candidate_payload.get("operation_log", [])
    decision["next_plan"] = candidate_payload.get("next_plan") or build_next_plan(
        candidate_payload.get("diagnostics", {}).get("decision", {})
    )
    decision["continuation"] = _continuation_payload(decision)
    decision["run_id"] = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}/autopilot-{uuid4().hex[:12]}"
    paths = write_autopilot_report(
        args.report_root,
        decision,
        decision["run_id"],
        operation_log=decision["operation_log"],
        next_plan=decision["next_plan"],
    )
    if args.git_release and decision.get("status") == "published":
        decision["git_release"] = {
            "branch": args.branch,
            "commit": _create_git_release(args.branch, args.version_root, paths),
        }
        paths = write_autopilot_report(
            args.report_root,
            decision,
            decision["run_id"],
            operation_log=decision["operation_log"],
            next_plan=decision["next_plan"],
        )
    print(json.dumps({"decision": decision, "report_paths": {key: str(value) for key, value in paths.items()}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
