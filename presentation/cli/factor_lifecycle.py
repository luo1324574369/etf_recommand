"""因子生命周期的月度监控和季度发布 CLI。"""

from __future__ import annotations

import argparse
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
    published = service.publish_quarterly(args.candidate_id, args.publish_date)
    print(f"因子已发布: {published.name}@{published.version}")


if __name__ == "__main__":
    main()
