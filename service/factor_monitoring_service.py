"""月度因子健康检查和替换候选报告。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from strategy.factor_lifecycle import FactorHealthMonitor, FactorHealthReport


@dataclass(frozen=True)
class MonthlyFactorReport:
    as_of_date: str
    reports: tuple[FactorHealthReport, ...]
    replacement_candidates: tuple[str, ...]
    watchlist: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "as_of_date": self.as_of_date,
            "reports": [
                {
                    "factor_name": report.factor_name,
                    "status": report.status,
                    "window_months": report.window_months,
                    "metrics": report.metrics,
                    "failed_metrics": list(report.failed_metrics),
                }
                for report in self.reports
            ],
            "replacement_candidates": list(self.replacement_candidates),
            "watchlist": list(self.watchlist),
        }

    def write(self, output_root: str | Path) -> dict[str, Path]:
        output_directory = Path(output_root)
        output_directory.mkdir(parents=True, exist_ok=True)
        json_path = output_directory / "factor-health-report.json"
        markdown_path = output_directory / "factor-health-report.md"
        json_path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(self.to_markdown(), encoding="utf-8")
        return {"json": json_path, "markdown": markdown_path}

    def to_markdown(self) -> str:
        lines = [
            "# 月度因子健康报告",
            "",
            f"- 截止日期：`{self.as_of_date}`",
            f"- 替换候选：`{', '.join(self.replacement_candidates) or '无'}`",
            f"- 观察名单：`{', '.join(self.watchlist) or '无'}`",
            "",
            "## 因子状态",
            "",
            "| 因子 | 状态 | 窗口（月） | 失败指标 |",
            "|---|---|---:|---|",
        ]
        for report in self.reports:
            lines.append(
                f"| {report.factor_name} | {report.status} | {report.window_months} | "
                f"{', '.join(report.failed_metrics) or '无'} |"
            )
        lines.extend([
            "",
            "## 执行规则",
            "",
            "替换候选只进入候选因子 OOS 流程，不得直接改写正式因子；新因子必须完成 12/24 个月 OOS、人工审批和影子运行。",
            "",
        ])
        return "\n".join(lines)


class MonthlyFactorMonitor:
    def __init__(self, health_monitor: FactorHealthMonitor | None = None):
        self.health_monitor = health_monitor or FactorHealthMonitor()

    def evaluate(
        self,
        observations_by_factor: dict[str, list[dict]],
        as_of_date: str,
    ) -> MonthlyFactorReport:
        date.fromisoformat(as_of_date)
        reports = tuple(
            self.health_monitor.evaluate(name, observations)
            for name, observations in sorted(observations_by_factor.items())
        )
        replacement_candidates = tuple(
            report.factor_name
            for report in reports
            if report.status == "failure_candidate"
        )
        watchlist = tuple(
            report.factor_name
            for report in reports
            if report.status in {"attention", "warning"}
        )
        return MonthlyFactorReport(
            as_of_date=as_of_date,
            reports=reports,
            replacement_candidates=replacement_candidates,
            watchlist=watchlist,
        )


def load_observations(path: str | Path) -> dict[str, list[dict]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, dict) and "observations" in value:
        value = value["observations"]
    if not isinstance(value, dict):
        raise ValueError("observations JSON must be an object keyed by factor name")
    return {str(name): list(rows) for name, rows in value.items()}
