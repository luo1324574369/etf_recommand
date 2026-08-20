import sys
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
    candidate = service.submit_candidate(definition, score=0.8)

    with pytest.raises(ValueError, match="12-month OOS"):
        service.approve_candidate(candidate.candidate_id, "tester")

    service.record_oos(candidate.candidate_id, 12, True)
    with pytest.raises(ValueError, match="24-month OOS"):
        service.approve_candidate(candidate.candidate_id, "tester")
    service.record_oos(candidate.candidate_id, 24, True)
    service.approve_candidate(candidate.candidate_id, "tester")
    service.start_shadow_run(candidate.candidate_id, "2025-01-01", "2025-03-31")

    with pytest.raises(ValueError, match="shadow"):
        service.publish_quarterly(candidate.candidate_id, "2025-04-01")

    service.complete_shadow_run(candidate.candidate_id, {"excess_return": 0.02})
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
