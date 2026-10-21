"""The instructions AI tools read must keep up with the CLI and the rules."""
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "ledger-capture" / "SKILL.md"
BLOCK = REPO / "skills" / "ledger-capture" / "agents-block.md"


def _installer():
    spec = importlib.util.spec_from_file_location("inst", REPO / "scripts" / "install_instructions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_skill_mentions_every_verb_and_the_rules():
    text = SKILL.read_text()
    for needle in ("ledger rules", "ledger ship", "ledger idea", "--note", "ledger done",
                   "capture the missed sessions", "commit message"):
        assert needle in text, needle
    assert "noun-first" not in text.lower()
    assert "existing voice" not in text.lower()


def test_agents_block_mentions_every_verb_and_the_rules():
    text = BLOCK.read_text()
    assert text.startswith("## Ledger")
    for needle in ("ledger rules", "ledger status", "ledger ship", "ledger idea", "--note", "ledger done"):
        assert needle in text, needle


def test_replace_section_swaps_only_the_ledger_section():
    inst = _installer()
    before = "# Title\n\nIntro.\n\n## Ledger — old\n\nold text\n\n## Other\n\nkeep me\n"
    out = inst.replace_section(before, "## Ledger: new\n\nnew text\n")
    assert out == "# Title\n\nIntro.\n\n## Ledger: new\n\nnew text\n\n## Other\n\nkeep me\n"
    assert inst.replace_section(out, "## Ledger: new\n\nnew text\n") == out  # idempotent


def test_replace_section_at_end_and_missing():
    inst = _installer()
    assert inst.replace_section("# T\n\n## Ledger x\n\nold\n", "## Ledger: new\n") == "# T\n\n## Ledger: new\n"
    assert inst.replace_section("# T\n", "## Ledger: new\n") == "# T\n\n## Ledger: new\n"
