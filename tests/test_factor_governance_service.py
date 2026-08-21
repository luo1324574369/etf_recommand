import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_candidate_requires_oos_approval_and_shadow_before_publish(tmp_path):
    from service.factor_governance_service import FactorGovernanceService
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    registry = FactorRegistry(tmp_path / "factors.json")
    service = FactorGovernanceService(tmp_path / "candidates.json", registry)
    definition = FactorDefinition(
        name="new_value",
        version="1.0.0",
        direction=-1,
        dependencies=("pe",),
        source="plugin",
    )
    candidate = service.submit_candidate(
        definition,
        score=0.8,
        evidence={"governance_checks": {
            "correlation": True,
            "marginal_contribution": True,
            "industry_exposure": True,
            "style_exposure": True,
        }},
    )

    with pytest.raises(ValueError, match="12-month OOS"):
        service.approve_candidate(candidate.candidate_id, "tester")

    service.record_oos(candidate.candidate_id, 12, True, {
        "start_date": "2024-01-01", "end_date": "2024-12-31", "metrics": {"icir": 0.4}
    })
    with pytest.raises(ValueError, match="24-month OOS"):
        service.approve_candidate(candidate.candidate_id, "tester")
    service.record_oos(candidate.candidate_id, 24, True, {
        "start_date": "2023-01-01", "end_date": "2024-12-31", "metrics": {"icir": 0.4}
    })
    service.approve_candidate(candidate.candidate_id, "tester")
    service.start_shadow_run(candidate.candidate_id, "2025-01-01", "2025-03-31")

    with pytest.raises(ValueError, match="shadow"):
        service.publish_quarterly(candidate.candidate_id, "2025-04-01")

    service.complete_shadow_run(candidate.candidate_id, {
        "source": "formal_backtest", "run_id": "shadow-run-1", "status": "passed",
        "data_range": {"start_date": "2025-01-01", "end_date": "2025-03-31"},
        "excess_return": 0.02,
    })
    published = service.publish_quarterly(candidate.candidate_id, "2025-04-01")

    assert published.status == "active"
    assert service.get_candidate(candidate.candidate_id).stage == "active"


def test_candidate_persists_evidence_for_static_review(tmp_path):
    from service.factor_governance_service import FactorGovernanceService
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    service = FactorGovernanceService(
        tmp_path / "candidates.json",
        FactorRegistry(tmp_path / "factors.json"),
    )
    candidate = service.submit_candidate(
        FactorDefinition(
            name="ai_value",
            version="1.0.0",
            direction=-1,
            dependencies=("pe",),
            source="ai_generated",
        ),
        score=0.7,
        evidence={"source_hash": "sha256:abc", "evaluator_version": "static-v1"},
    )

    reloaded = FactorGovernanceService(
        tmp_path / "candidates.json",
        FactorRegistry(tmp_path / "factors.json"),
    ).get_candidate(candidate.candidate_id)
    assert reloaded.evidence["source_hash"] == "sha256:abc"


def test_shadow_window_and_rollback_are_persisted(tmp_path):
    from service.factor_governance_service import FactorGovernanceService
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    registry = FactorRegistry(tmp_path / "factors.json")
    service = FactorGovernanceService(tmp_path / "candidates.json", registry)
    first = FactorDefinition("value", "1.0.0", -1, ("pe",), "plugin")
    second = FactorDefinition("value", "2.0.0", -1, ("pb",), "plugin")
    registry.register(first)
    registry.request_approval(first.name, first.version)
    registry.activate(first.name, first.version, "tester")
    candidate = service.submit_candidate(
        second,
        score=0.8,
        evidence={"governance_checks": {
            "correlation": True,
            "marginal_contribution": True,
            "industry_exposure": True,
            "style_exposure": True,
        }},
    )
    service.record_oos(candidate.candidate_id, 12, True, {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "metrics": {"icir": 0.4}, "period": "2024",
    })
    service.record_oos(candidate.candidate_id, 24, True, {
        "start_date": "2023-01-01", "end_date": "2024-12-31",
        "metrics": {"icir": 0.4}, "period": "2023-2024",
    })
    service.approve_candidate(candidate.candidate_id, "tester")
    service.start_shadow_run(candidate.candidate_id, "2025-01-01", "2025-03-31")

    shadow = service.get_candidate(candidate.candidate_id)
    assert shadow.shadow_start_date == "2025-01-01"
    assert shadow.shadow_end_date == "2025-03-31"
    assert shadow.oos_results[12]["period"] == "2024"

    service.complete_shadow_run(candidate.candidate_id, {
        "source": "formal_backtest", "run_id": "shadow-run-1", "status": "passed",
        "data_range": {"start_date": "2025-01-01", "end_date": "2025-03-31"},
        "excess_return": 0.02,
    })
    service.publish_quarterly(candidate.candidate_id, "2025-04-01")
    rolled_back = service.rollback_factor(
        "value", "1.0.0", operator="tester", reason="shadow drawdown breach"
    )

    assert rolled_back.status == "active"
    audit = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    assert any(item.get("stage") == "rolled_back" for item in audit)
