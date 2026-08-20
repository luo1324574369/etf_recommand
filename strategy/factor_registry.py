"""版本化因子定义和人工审批状态。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    version: str
    direction: int
    dependencies: tuple[str, ...]
    source: str
    status: str = "draft"
    approved_by: str | None = None

    def to_dict(self) -> dict:
        value = asdict(self)
        value["dependencies"] = list(self.dependencies)
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "FactorDefinition":
        return cls(
            name=value["name"],
            version=value["version"],
            direction=int(value["direction"]),
            dependencies=tuple(value.get("dependencies", [])),
            source=value["source"],
            status=value.get("status", "draft"),
            approved_by=value.get("approved_by"),
        )


class FactorRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._definitions: dict[tuple[str, str], FactorDefinition] = {}
        self._load()

    def register(self, definition: FactorDefinition) -> FactorDefinition:
        key = (definition.name, definition.version)
        if key in self._definitions:
            raise ValueError(f"factor version already exists: {definition.name}@{definition.version}")
        if definition.source not in {"builtin", "plugin", "ai_generated"}:
            raise ValueError(f"unsupported factor source: {definition.source}")
        self._definitions[key] = definition
        self._save()
        return definition

    def get(self, name: str, version: str) -> FactorDefinition:
        try:
            return self._definitions[(name, version)]
        except KeyError as error:
            raise KeyError(f"factor version not found: {name}@{version}") from error

    def request_approval(self, name: str, version: str) -> FactorDefinition:
        definition = self.get(name, version)
        updated = replace(definition, status="approved")
        self._definitions[(name, version)] = updated
        self._save()
        return updated

    def activate(self, name: str, version: str, approved_by: str) -> FactorDefinition:
        definition = self.get(name, version)
        if definition.status != "approved":
            raise ValueError("factor must be approved before activation")
        for key, existing in list(self._definitions.items()):
            if existing.name == name and existing.status == "active":
                self._definitions[key] = replace(existing, status="retired")
        activated = replace(definition, status="active", approved_by=approved_by)
        self._definitions[(name, version)] = activated
        self._save()
        return activated

    def rollback(self, name: str, target_version: str) -> FactorDefinition:
        target = self.get(name, target_version)
        if target.status not in {"approved", "retired", "active"}:
            raise ValueError("rollback target must be approved or previously active")
        for key, existing in list(self._definitions.items()):
            if existing.name == name and existing.status == "active":
                self._definitions[key] = replace(existing, status="retired")
        rolled_back = replace(target, status="active")
        self._definitions[(name, target_version)] = rolled_back
        self._save()
        return rolled_back

    def _load(self) -> None:
        if not self.path.exists():
            return
        values = json.loads(self.path.read_text(encoding="utf-8"))
        self._definitions = {
            (value["name"], value["version"]): FactorDefinition.from_dict(value)
            for value in values
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        values = [
            definition.to_dict()
            for _, definition in sorted(self._definitions.items())
        ]
        self.path.write_text(
            json.dumps(values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
