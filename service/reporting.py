"""生成可审计、可供 AI 阅读的运行报告。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any

import pandas as pd


def _json_default(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, pd.DataFrame):
        return value.to_dict(orient="records")
    if isinstance(value, pd.Series):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_payload(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    status: str
    params: dict[str, Any]
    data_quality: dict[str, Any]
    git_revision: str
    created_at: str

    @classmethod
    def from_result(
        cls,
        run_id: str,
        status: str,
        params: dict[str, Any],
        data_quality: dict[str, Any],
        git_revision: str,
    ) -> "RunManifest":
        return cls(
            run_id=run_id,
            status=status,
            params=_json_payload(params),
            data_quality=_json_payload(data_quality),
            git_revision=git_revision,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReportArtifact:
    @staticmethod
    def write(output_root: str | Path, manifest: RunManifest, result: dict[str, Any]) -> dict[str, Path]:
        output_directory = Path(output_root) / manifest.run_id
        output_directory.mkdir(parents=True, exist_ok=True)
        normalized_result = _json_payload(result)
        data_payload = {
            "run_id": manifest.run_id,
            "status": manifest.status,
            "manifest": manifest.to_dict(),
            "result": normalized_result,
        }

        manifest_path = output_directory / "run-manifest.json"
        data_path = output_directory / "report-data.json"
        markdown_path = output_directory / "report.md"
        html_path = output_directory / "report.html"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        data_path.write_text(
            json.dumps(data_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(
            _render_markdown(manifest, normalized_result),
            encoding="utf-8",
        )
        html_path.write_text(
            _render_html(manifest, normalized_result),
            encoding="utf-8",
        )
        return {
            "manifest": manifest_path,
            "data": data_path,
            "markdown": markdown_path,
            "html": html_path,
        }


def _render_markdown(manifest: RunManifest, result: dict[str, Any]) -> str:
    if manifest.status == "blocked":
        conclusion = "数据质量阻断：不得生成模拟订单。请先修复报告中的数据问题。"
    else:
        conclusion = "数据质量通过：本报告记录回测事实，行动建议必须结合风险和触发条件。"
    return "\n".join([
        "# ETF 模拟交易运行报告",
        "",
        f"- 运行 ID：`{manifest.run_id}`",
        f"- 状态：`{manifest.status}`",
        f"- 代码版本：`{manifest.git_revision}`",
        f"- 生成时间：`{manifest.created_at}`",
        "",
        "## 结论摘要",
        "",
        conclusion,
        "",
        "## 数据可信度",
        "",
        json.dumps(manifest.data_quality, ensure_ascii=False, indent=2),
        "",
        "## 策略配置",
        "",
        json.dumps(manifest.params, ensure_ascii=False, indent=2),
        "",
        "## 运行事实",
        "",
        json.dumps(result, ensure_ascii=False, indent=2),
        "",
        "## 风险与条件",
        "",
        "报告使用次日开盘价、固定滑点和手续费的模拟成交假设；不构成无条件买入或卖出指令。",
        "",
    ])


def _render_html(manifest: RunManifest, result: dict[str, Any]) -> str:
    markdown = _render_markdown(manifest, result)
    escaped = html.escape(markdown)
    return (
        "<!doctype html><html lang=\"zh-CN\"><head>"
        "<meta charset=\"utf-8\"><title>ETF 模拟交易运行报告</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
        "max-width:1100px;margin:32px auto;padding:0 20px;line-height:1.6}"
        "pre{white-space:pre-wrap;background:#f6f8fa;padding:16px;border-radius:8px}"
        "</style></head><body><h1>ETF 模拟交易运行报告</h1>"
        f"<pre>{escaped}</pre></body></html>"
    )
