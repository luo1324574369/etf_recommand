import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_registry_requires_approval_before_activation(tmp_path):
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    registry = FactorRegistry(tmp_path / "factors.json")
    definition = FactorDefinition(
        name="momentum_120d",
        version="2.0.0",
        direction=1,
        dependencies=("close",),
        source="ai_generated",
        status="draft",
    )
    registry.register(definition)

    with pytest.raises(ValueError, match="approved"):
        registry.activate(definition.name, definition.version, approved_by="tester")

    registry.request_approval(definition.name, definition.version)
    activated = registry.activate(definition.name, definition.version, approved_by="tester")

    assert activated.status == "active"
    assert activated.approved_by == "tester"


def test_registry_rollback_keeps_previous_version(tmp_path):
    from strategy.factor_registry import FactorDefinition, FactorRegistry

    registry = FactorRegistry(tmp_path / "factors.json")
    for version in ("1.0.0", "2.0.0"):
        registry.register(FactorDefinition(
            name="value",
            version=version,
            direction=-1,
            dependencies=("pe",),
            source="builtin",
            status="approved",
        ))
    registry.activate("value", "2.0.0", approved_by="tester")

    rolled_back = registry.rollback("value", "1.0.0")

    assert rolled_back.version == "1.0.0"
    assert rolled_back.status == "active"
    assert registry.get("value", "2.0.0").status == "retired"
