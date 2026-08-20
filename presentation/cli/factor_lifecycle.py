"""因子生命周期的月度监控和季度发布 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.factor_governance_service import FactorGovernanceService
from service.factor_monitoring_service import MonthlyFactorMonitor, load_observations
from strategy.factor_registry import FactorRegistry


def main():
    parser = argparse.ArgumentParser(description="运行因子月度监控或季度发布")
    subparsers = parser.add_subparsers(dest="command", required=True)

    monitor = subparsers.add_parser("monthly-monitor", help="生成月度因子健康报告")
    monitor.add_argument("--observations", required=True, help="按因子分组的观测 JSON")
    monitor.add_argument("--as-of-date", required=True)
    monitor.add_argument("--output", required=True)

    publish = subparsers.add_parser("quarterly-publish", help="发布已完成影子运行的候选因子")
    publish.add_argument("--candidates", required=True)
    publish.add_argument("--registry", required=True)
    publish.add_argument("--candidate-id", required=True)
    publish.add_argument("--publish-date", required=True)

    oos = subparsers.add_parser("record-oos", help="记录候选因子 OOS 结果")
    oos.add_argument("--candidates", required=True)
    oos.add_argument("--registry", required=True)
    oos.add_argument("--candidate-id", required=True)
    oos.add_argument("--months", type=int, choices=(12, 24), required=True)
    oos.add_argument("--passed", action="store_true")

    approve = subparsers.add_parser("approve", help="人工批准候选因子")
    approve.add_argument("--candidates", required=True)
    approve.add_argument("--registry", required=True)
    approve.add_argument("--candidate-id", required=True)
    approve.add_argument("--approver", required=True)

    shadow = subparsers.add_parser("start-shadow", help="启动候选因子影子运行")
    shadow.add_argument("--candidates", required=True)
    shadow.add_argument("--registry", required=True)
    shadow.add_argument("--candidate-id", required=True)
    shadow.add_argument("--start-date", required=True)
    shadow.add_argument("--end-date", required=True)

    complete_shadow = subparsers.add_parser("complete-shadow", help="完成影子运行并记录指标")
    complete_shadow.add_argument("--candidates", required=True)
    complete_shadow.add_argument("--registry", required=True)
    complete_shadow.add_argument("--candidate-id", required=True)
    complete_shadow.add_argument("--metrics", required=True, help="影子指标 JSON 文件")

    args = parser.parse_args()
    if args.command == "monthly-monitor":
        report = MonthlyFactorMonitor().evaluate(
            load_observations(args.observations),
            args.as_of_date,
        )
        paths = report.write(args.output)
        print(f"月度因子报告已生成: {paths['markdown']}")
        return

    service = FactorGovernanceService(
        Path(args.candidates),
        FactorRegistry(Path(args.registry)),
    )
    if args.command == "record-oos":
        candidate = service.record_oos(args.candidate_id, args.months, args.passed)
        print(f"OOS 状态已记录: {candidate.candidate_id} -> {candidate.stage}")
    elif args.command == "approve":
        candidate = service.approve_candidate(args.candidate_id, args.approver)
        print(f"因子已批准进入影子运行: {candidate.candidate_id}")
    elif args.command == "start-shadow":
        candidate = service.start_shadow_run(args.candidate_id, args.start_date, args.end_date)
        print(f"影子运行已启动: {candidate.candidate_id}")
    elif args.command == "complete-shadow":
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
        candidate = service.complete_shadow_run(args.candidate_id, metrics)
        print(f"影子运行已完成: {candidate.candidate_id} -> {candidate.stage}")
    else:
        published = service.publish_quarterly(args.candidate_id, args.publish_date)
        print(f"因子已发布: {published.name}@{published.version}")


if __name__ == "__main__":
    main()
