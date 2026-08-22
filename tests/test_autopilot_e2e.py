import json
from pathlib import Path
import subprocess
import sys


def _metrics(**overrides):
    value = {
        "data_quality_passed": True,
        "future_safe": True,
        "oos_12_excess_return": 1.0,
        "oos_24_excess_return": 2.0,
        "oos_sharpe": 0.5,
        "max_drawdown": 25.0,
        "annual_turnover": 120.0,
        "oos_stability": 0.6,
        "annual_return": 12.0,
        "stress_passed": True,
        "final_holdout_passed": True,
    }
    value.update(overrides)
    return value


def test_autopilot_cli_publishes_and_archives_decision(tmp_path):
    repository_root = Path(__file__).resolve().parent.parent
    candidates_path = tmp_path / "candidates.json"
    candidates_path.write_text(json.dumps({
        "baseline_metrics": _metrics(),
        "candidates": [{
            "config": {"params": {"top_n": 4}},
            "metrics": _metrics(
                oos_12_excess_return=3.0,
                oos_24_excess_return=5.0,
                oos_sharpe=0.9,
                max_drawdown=18.0,
                oos_stability=0.9,
                annual_return=20.0,
            ),
        }],
    }), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_autopilot.py",
            "--candidates", str(candidates_path),
            "--version-root", str(tmp_path / "versions"),
            "--report-root", str(tmp_path / "reports"),
            "--branch", "codex/autopilot/e2e",
            "--allow-unverified-input",
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(completed.stdout)

    assert output["decision"]["status"] == "published"
    assert Path(output["report_paths"]["data"]).exists()
    assert (tmp_path / "versions" / "active-config.json").exists()
    assert output["decision"]["published"]["previous_version_id"] == "baseline"
    assert Path(output["report_paths"]["operation_log"]).exists()
    assert Path(output["report_paths"]["next_plan"]).exists()
