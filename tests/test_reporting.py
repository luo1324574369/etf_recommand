import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_report_archive_contains_machine_readable_and_human_files(tmp_path):
    from service.reporting import ReportArtifact, RunManifest

    manifest = RunManifest.from_result(
        run_id="run-001",
        status="passed",
        params={"top_n": 3},
        data_quality={"status": "passed", "snapshot_id": "snap-001"},
        git_revision="abc123",
    )
    result = {
        "final_value": 1_050_000,
        "total_return": 5.0,
        "trade_list": [],
        "factor_diagnostics": {"weight_mode": "static"},
    }

    paths = ReportArtifact.write(tmp_path, manifest, result)

    assert {path.name for path in paths.values()} == {
        "run-manifest.json", "report-data.json", "report.md", "report.html",
    }
    assert json.loads(paths["data"].read_text(encoding="utf-8"))["status"] == "passed"
    assert "数据可信度" in paths["markdown"].read_text(encoding="utf-8")
    assert "ETF 模拟交易运行报告" in paths["html"].read_text(encoding="utf-8")


def test_blocked_report_does_not_claim_trade_advice(tmp_path):
    from service.reporting import ReportArtifact, RunManifest

    manifest = RunManifest.from_result(
        run_id="run-blocked",
        status="blocked",
        params={},
        data_quality={"status": "blocked", "issues": [{"rule": "ohlc_relation"}]},
        git_revision="abc123",
    )
    paths = ReportArtifact.write(tmp_path, manifest, {})

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "不得生成模拟订单" in markdown
