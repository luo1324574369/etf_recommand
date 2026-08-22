import json

import pytest


def _metrics(**overrides):
    metrics = {
        "data_quality_passed": True,
        "future_safe": True,
        "oos_12_excess_return": 2.0,
        "oos_24_excess_return": 4.0,
        "oos_sharpe": 0.8,
        "max_drawdown": 20.0,
        "annual_turnover": 120.0,
        "oos_stability": 0.8,
        "annual_return": 18.0,
        "stress_passed": True,
    }
    metrics.update(overrides)
    return metrics


def test_candidate_score_requires_hard_gates_and_improves_baseline():
    from service.autopilot_service import score_candidate

    evaluation = score_candidate(
        {"top_n": 4},
        _metrics(),
        baseline_metrics=_metrics(
            oos_12_excess_return=0.5,
            oos_24_excess_return=1.0,
            oos_sharpe=0.4,
            max_drawdown=25.0,
            annual_return=12.0,
            oos_stability=0.6,
        ),
    )

    assert evaluation.accepted is True
    assert evaluation.score > evaluation.baseline_score
    assert evaluation.score_improvement_pct >= 5.0
    assert evaluation.reasons == ()


def test_candidate_score_rejects_oos_and_drawdown_failures():
    from service.autopilot_service import score_candidate

    evaluation = score_candidate(
        {"top_n": 4},
        _metrics(oos_12_excess_return=-1.0, max_drawdown=36.0),
        baseline_metrics=_metrics(),
    )

    assert evaluation.accepted is False
    assert "oos_12_excess_return" in evaluation.reasons
    assert "max_drawdown" in evaluation.reasons


def test_version_store_publishes_and_rolls_back_with_hash_lock(tmp_path):
    from service.autopilot_service import StrategyVersionStore

    store = StrategyVersionStore(tmp_path / "versions")
    baseline = {"params": {"top_n": 3}, "factor_weights": {"momentum": 1.0}}
    store.initialize(baseline, commit="base-commit")
    published = store.publish(
        {"params": {"top_n": 4}, "factor_weights": {"momentum": 0.8, "value": 0.2}},
        evaluation={"score": 82.0, "score_improvement_pct": 8.0},
        commit="candidate-commit",
        branch="codex/autopilot/test-run",
    )

    assert store.load_active()["version_id"] == published["version_id"]
    assert store.is_hash_published(published["config_hash"])

    rollback = store.rollback("max drawdown breach")
    assert rollback["version_id"] == "baseline"
    assert store.is_hash_locked(published["config_hash"])
    assert json.loads((tmp_path / "versions" / "release-history.json").read_text())[-1]["event"] == "rollback"

    with pytest.raises(ValueError, match="rollback-locked"):
        store.publish(
            {"params": {"top_n": 4}, "factor_weights": {"momentum": 0.8, "value": 0.2}},
            evaluation={"score": 90.0},
            commit="candidate-commit-2",
            branch="codex/autopilot/test-run-2",
        )


def test_autopilot_keeps_active_version_when_no_candidate_passes(tmp_path):
    from service.autopilot_service import AutopilotService, StrategyVersionStore

    store = StrategyVersionStore(tmp_path / "versions")
    store.initialize({"params": {"top_n": 3}}, commit="base-commit")
    service = AutopilotService(store)

    decision = service.evaluate_and_publish(
        [{"config": {"params": {"top_n": 4}}, "metrics": _metrics(oos_sharpe=0.1)}],
        baseline_metrics=_metrics(),
        commit="candidate-commit",
        branch="codex/autopilot/test-run",
    )

    assert decision["status"] == "kept_current"
    assert decision["published"] is None
    assert store.load_active()["version_id"] == "baseline"


def test_autopilot_evaluates_later_candidates_before_selecting_best(tmp_path):
    from service.autopilot_service import AutopilotService, StrategyVersionStore

    store = StrategyVersionStore(tmp_path / "versions")
    store.initialize({"params": {"top_n": 3}}, commit="base-commit")
    candidates = [
        {"config": {"params": {"top_n": 4}}, "metrics": _metrics()},
        {"config": {"params": {"top_n": 5}}, "metrics": _metrics(oos_sharpe=0.1)},
        {"config": {"params": {"top_n": 6}}, "metrics": _metrics(oos_sharpe=0.1)},
        {"config": {"params": {"top_n": 7}}, "metrics": _metrics(oos_sharpe=0.1)},
        {
            "config": {"params": {"top_n": 8}},
            "metrics": _metrics(
                oos_12_excess_return=5.0,
                oos_24_excess_return=7.0,
                oos_sharpe=1.2,
                max_drawdown=15.0,
                annual_return=25.0,
                oos_stability=1.0,
            ),
        },
    ]

    decision = AutopilotService(store).evaluate_and_publish(
        candidates,
        baseline_metrics=_metrics(),
        commit="candidate-commit",
        branch="codex/autopilot/test-run",
    )

    assert len(decision["evaluations"]) == 5
    assert decision["status"] == "published"
    assert store.load_active()["config"]["params"]["top_n"] == 8
    assert decision["budget"]["selection_method"] == "evaluate_all_within_budget_then_rank_accepted"


def test_selection_oos_does_not_rank_candidates_by_final_holdout(tmp_path):
    from service.autopilot_service import AutopilotService, StrategyVersionStore

    store = StrategyVersionStore(tmp_path / "versions")
    store.initialize({"params": {"top_n": 3}}, commit="base-commit")
    baseline = _metrics()
    baseline["selection_metrics"] = _metrics()
    candidates = [
        {
            "config": {"params": {"top_n": 4}},
            "metrics": {
                **_metrics(
                    oos_12_excess_return=-20.0,
                    final_holdout_passed=False,
                ),
                "selection_metrics": _metrics(
                    oos_12_excess_return=3.0,
                    oos_24_excess_return=6.0,
                    oos_sharpe=1.2,
                    annual_return=24.0,
                ),
                "final_holdout_metrics": {
                    "available": True,
                    "oos_12_excess_return": -20.0,
                    "oos_sharpe": -0.5,
                    "max_drawdown": 20.0,
                },
            },
        },
        {
            "config": {"params": {"top_n": 5}},
            "metrics": {
                **_metrics(
                    oos_12_excess_return=4.0,
                    oos_24_excess_return=4.0,
                    oos_sharpe=0.8,
                ),
                "selection_metrics": _metrics(
                    oos_12_excess_return=1.0,
                    oos_24_excess_return=1.0,
                    oos_sharpe=0.5,
                ),
                "final_holdout_metrics": {
                    "available": True,
                    "oos_12_excess_return": 4.0,
                    "oos_sharpe": 0.8,
                    "max_drawdown": 20.0,
                },
            },
        },
    ]

    decision = AutopilotService(store).evaluate_and_publish(
        candidates,
        baseline_metrics=baseline,
        commit="candidate-commit",
        branch="codex/autopilot/test-run",
        selection_only=True,
    )

    assert decision["status"] == "kept_current"
    assert decision["reason"] == "selected_candidate_failed_final_holdout"
    assert "final_holdout_excess_return" in decision["evaluations"][0]["reasons"]
    assert store.load_active()["version_id"] == "baseline"


def test_autopilot_rolls_back_on_hard_risk_breach(tmp_path):
    from service.autopilot_service import AutopilotService, StrategyVersionStore

    store = StrategyVersionStore(tmp_path / "versions")
    store.initialize({"params": {"top_n": 3}}, commit="base-commit")
    published = store.publish(
        {"params": {"top_n": 4}},
        evaluation={"score": 82.0},
        commit="candidate-commit",
        branch="codex/autopilot/test-run",
    )
    result = AutopilotService(store).rollback_if_needed(
        {"data_quality_passed": True, "future_safe": True, "max_drawdown": 36.0},
        baseline_metrics=_metrics(),
    )

    assert result["status"] == "rolled_back"
    assert result["rolled_back"]["version_id"] == "baseline"
    assert store.is_hash_locked(published["config_hash"])


def test_factor_candidate_can_be_auto_published_after_oos(tmp_path):
    from service.factor_governance_service import FactorGovernanceService
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    service = FactorGovernanceService(
        tmp_path / "candidates.json",
        FactorRegistry(tmp_path / "registry.json"),
    )
    candidate = service.submit_candidate(
        FactorDefinition("autonomous_value", "1.0.0", -1, ("pe",), "ai_generated"),
        score=0.8,
        evidence={"governance_checks": {
            "correlation": True,
            "marginal_contribution": True,
            "industry_exposure": True,
            "style_exposure": True,
        }, "sandbox": {"passed": True, "source_hash": "abc123"}},
    )
    service.record_oos(candidate.candidate_id, 12, True, {
        "start_date": "2024-01-01", "end_date": "2024-12-31", "metrics": _metrics()
    })
    service.record_oos(candidate.candidate_id, 24, True, {
        "start_date": "2023-01-01", "end_date": "2024-12-31", "metrics": _metrics()
    })

    published = service.auto_publish(candidate.candidate_id)

    assert published.status == "active"
    assert service.get_candidate(candidate.candidate_id).approved_by == "codex-autopilot"
