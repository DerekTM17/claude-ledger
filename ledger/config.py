"""Load ~/.config/ledger/projects.yaml for discovery overrides."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LedgerConfig:
    include: list[dict[str, Any]] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    memory_overrides: dict[str, str] = field(default_factory=dict)


def load_config(path: Path) -> LedgerConfig:
    if not path.exists():
        return LedgerConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LedgerConfig(
        include=data.get("include", []) or [],
        exclude=data.get("exclude", []) or [],
        memory_overrides=data.get("memory_overrides", {}) or {},
    )


def default_config_path() -> Path:
    return Path.home() / ".config" / "ledger" / "projects.yaml"


def default_state_path() -> Path:
    return Path.home() / ".config" / "ledger" / "state.json"
