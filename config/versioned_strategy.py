"""读取自主优化使用的版本化策略配置。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.settings import PARAM_PRESETS


DEFAULT_VERSION_ROOT = Path(__file__).resolve().parent / "strategy_versions"


def default_strategy_config() -> dict[str, Any]:
    return {
        "params": dict(PARAM_PRESETS["多因子轮动"][0]["params"]),
        "factor_weights": {},
        "constraints": {},
    }


def load_active_strategy_config(root: str | Path = DEFAULT_VERSION_ROOT) -> dict[str, Any]:
    active_path = Path(root) / "active-config.json"
    if not active_path.exists():
        return {
            "version_id": "unversioned-default",
            "config": default_strategy_config(),
            "config_hash": None,
        }
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    if "config" not in payload or not isinstance(payload["config"], dict):
        raise ValueError(f"invalid active strategy config: {active_path}")
    if payload.get("config_hash"):
        from service.autopilot_service import configuration_hash

        expected_hash = configuration_hash(payload["config"])
        if payload["config_hash"] != expected_hash:
            raise ValueError(f"active strategy config hash mismatch: {active_path}")
    return payload
