from pathlib import Path

from ledger.memory import claude_slug, memory_path_for, read_description


def test_memory_path_dash_to_underscore(tmp_path):
    p = memory_path_for("congressional-dashboard", memory_root=tmp_path)
    assert p == tmp_path / "project_congressional_dashboard.md"


def test_memory_path_override(tmp_path):
    p = memory_path_for("netgraph-ai", memory_root=tmp_path,
                        override="project_netgraph_ai.md")
    assert p == tmp_path / "project_netgraph_ai.md"


def test_memory_path_default_root_follows_home(tmp_path, monkeypatch):
    """The default root must be resolved at call time, not import time, so
    a test's HOME override actually isolates it from the real ~/.claude."""
    monkeypatch.setenv("HOME", str(tmp_path))
    p = memory_path_for("alpha")
    assert p == tmp_path / ".claude" / "projects" / claude_slug(tmp_path) / "memory" / "project_alpha.md"


def test_read_description_from_frontmatter(tmp_path):
    f = tmp_path / "project_x.md"
    f.write_text(
        '---\n'
        'name: x\n'
        'description: "X project — phase 2 complete"\n'
        'metadata:\n'
        '  type: project\n'
        '---\n'
        '\nBody first paragraph.\n'
    )
    assert read_description(f) == "X project — phase 2 complete"


def test_read_description_falls_back_to_first_body_line(tmp_path):
    f = tmp_path / "project_x.md"
    f.write_text("---\nname: x\n---\n\nFallback body line.\n\nMore.\n")
    assert read_description(f) == "Fallback body line."


def test_read_description_missing_file_returns_none(tmp_path):
    assert read_description(tmp_path / "absent.md") is None


def test_read_description_tolerates_unquoted_colon_in_value(tmp_path):
    """Real-world frontmatter: unquoted description with a mid-value colon
    breaks strict YAML, but the regex fallback should still recover it."""
    f = tmp_path / "project_x.md"
    f.write_text(
        "---\n"
        "name: x\n"
        "description: Public sector data. As of 2026-05-19 (tests): state-aggregate surfaced.\n"
        "type: project\n"
        "---\n"
        "\n# ═══════════════════════════════════════════════════════════════════\nbody.\n"
    )
    desc = read_description(f)
    assert desc is not None
    assert desc.startswith("Public sector data")
    assert "state-aggregate surfaced" in desc


def test_read_description_skips_body_decoration(tmp_path):
    """When falling back to body, skip lines that are just decoration
    (e.g. '# ════════════════' section dividers)."""
    f = tmp_path / "project_x.md"
    f.write_text(
        "---\nname: x\n---\n"
        "\n"
        "# ═══════════════════════════════════════════════════════════════════\n"
        "Real first paragraph here.\n"
    )
    assert read_description(f) == "Real first paragraph here."
