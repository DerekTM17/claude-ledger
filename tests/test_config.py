import textwrap
from pathlib import Path

import pytest

from ledger.config import LedgerConfig, load_config


def test_load_config_missing_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "absent.yaml")
    assert cfg == LedgerConfig(include=[], exclude=[], memory_overrides={})


def test_load_config_parses_include_exclude_overrides(tmp_path):
    f = tmp_path / "projects.yaml"
    f.write_text(textwrap.dedent("""
        include:
          - path: ~/AI-Projects-Core/ollama-desktop-extension
            slug: ollama-desktop
        exclude:
          - dashboards
        memory_overrides:
          netgraph-ai: project_netgraph_ai.md
    """))
    cfg = load_config(f)
    assert cfg.include[0]["slug"] == "ollama-desktop"
    assert "~/AI-Projects-Core" in cfg.include[0]["path"]
    assert cfg.exclude == ["dashboards"]
    assert cfg.memory_overrides == {"netgraph-ai": "project_netgraph_ai.md"}


def test_load_config_malformed_yaml_raises(tmp_path):
    f = tmp_path / "projects.yaml"
    f.write_text("include: [unclosed")
    with pytest.raises(Exception):
        load_config(f)
