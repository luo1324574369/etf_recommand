import pytest


def test_factor_sandbox_runs_candidate_without_registry_access():
    from service.factor_sandbox import FactorSandbox

    result = FactorSandbox().run(
        "def calculate(row):\n    return row['close'] / row['open'] - 1\n",
        [{"open": 10, "close": 11}],
    )

    assert result.values[0] == pytest.approx(0.1)
    assert result.source_hash


def test_factor_sandbox_rejects_imports_and_times_out_infinite_code():
    from service.factor_sandbox import FactorSandbox

    with pytest.raises(ValueError, match="import"):
        FactorSandbox().run("import os\ndef calculate(row):\n    return 1\n", [{}])

    with pytest.raises(TimeoutError):
        FactorSandbox(timeout_seconds=0.2).run(
            "def calculate(row):\n    while True:\n        pass\n",
            [{}],
        )
