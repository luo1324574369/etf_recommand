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


def test_report_contains_static_ai_analysis_contract_and_history_comparison(tmp_path):
    from service.reporting import ReportArtifact, RunManifest

    manifest = RunManifest.from_result(
        run_id="run-static-ai",
        status="passed",
        params={"price_policy": "signal_adjusted_execution_raw"},
        data_quality={"status": "passed"},
        git_revision="abc123",
    )
    paths = ReportArtifact.write(tmp_path, manifest, {
        "final_value": 1_100_000,
        "historical_comparison": {
            "current_vs_previous": {"total_return": {"difference": 1.2}},
        },
        "factor_health": [{"factor_name": "momentum", "status": "healthy"}],
        "factor_candidates": [{"candidate_id": "candidate-1", "stage": "shadow"}],
    })

    payload = json.loads(paths["data"].read_text(encoding="utf-8"))
    assert payload["ai_analysis_contract"]["model_invocation"] == "external_manual"
    assert "运行对比" in paths["markdown"].read_text(encoding="utf-8")
    assert "因子治理" in paths["markdown"].read_text(encoding="utf-8")


def test_application_archive_adds_previous_run_context(tmp_path):
    from data.contracts import DataQualityReport
    from service.application_service import ApplicationService

    service = ApplicationService(
        tmp_path / "app.db",
        report_root=tmp_path / "reports",
    )
    try:
        first = service.archive_backtest_report(
            {"final_value": 1_000_000, "total_return": 0.0},
            {},
            DataQualityReport.passed("snapshot-1"),
        )
        service.archive_backtest_report(
            {"final_value": 1_020_000, "total_return": 2.0},
            {},
            DataQualityReport.passed("snapshot-2"),
        )
        payload = json.loads(first["data"].read_text(encoding="utf-8"))
        assert payload["manifest"]["params_hash"]
        assert payload["ai_analysis_contract"]["system_does_not_call_ai"] is True
    finally:
        service.close()
