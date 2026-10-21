import subprocess
from pathlib import Path

import pytest

from ledger import rules, writer
from ledger.models import Project

WHY = "It helps people find things faster."


def _proj(tmp_path: Path) -> Project:
    p = tmp_path / "alpha"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=p, check=True)
    (p / "docs").mkdir()
    (p / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n\n## Soon\n\n## Someday\n"
    )
    (p / "docs" / "CHANGELOG.md").write_text(
        "# alpha — Changelog\n\nIntro.\n"
    )
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=p, check=True)
    return Project(slug="alpha", path=p)


def test_add_backlog_item_writes_and_commits(tmp_path: Path):
    project = _proj(tmp_path)
    result = writer.add_backlog_item(project, "the new thing")

    assert result.committed is True
    content = project.backlog_path.read_text(encoding="utf-8")
    assert "the new thing" in content
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=project.path,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert "docs(backlog)" in log


def test_add_changelog_entry_writes_and_commits(tmp_path: Path):
    project = _proj(tmp_path)
    result = writer.add_changelog_entry(project, "Shipped the thing", why="why text")

    assert result.committed is True
    content = project.changelog_path.read_text(encoding="utf-8")
    assert "Shipped the thing" in content
    assert "why text" in content


def test_append_session_stub_writes_file_without_committing(tmp_path: Path):
    project = _proj(tmp_path)
    writer.append_session_stub(
        project,
        session_id="sid-12345678",
        branch="feature-x",
        diff_stat=" ledger/x.py | 4 ++--",
        commit_subjects=["abc123 feat: x"],
        last_user_msg="please add x",
    )

    sessions_path = project.docs_dir / "SESSIONS.md"
    assert sessions_path.exists()
    content = sessions_path.read_text(encoding="utf-8")
    assert "sid-1234" in content
    assert "feature-x" in content
    assert "ledger/x.py" in content
    assert "please add x" in content

    # CRITICAL: file is dirty (not committed) — the commit is deferred to
    # the next SessionStart by design (see spec §5).
    status = subprocess.run(
        ["git", "status", "--porcelain", "docs/SESSIONS.md"],
        cwd=project.path, capture_output=True, text=True, check=True,
    ).stdout
    assert "SESSIONS.md" in status


def test_promote_stub_marks_and_creates_changelog_entry(tmp_path: Path):
    project = _proj(tmp_path)
    writer.append_session_stub(
        project, session_id="sid-deadbeef", branch="main",
        diff_stat=" foo | 1 +", commit_subjects=["aaa feat: foo"],
        last_user_msg=None,
    )
    marker = "session `sid-dead`"  # the bit we use to locate the stub
    result = writer.promote_stub(project, marker, "Added foo", why="needed it")

    assert result.committed is True

    sessions = (project.docs_dir / "SESSIONS.md").read_text(encoding="utf-8")
    assert "✓" in sessions  # stub got the promoted tick
    changelog = project.changelog_path.read_text(encoding="utf-8")
    assert "Added foo" in changelog
    assert "needed it" in changelog


def test_changelog_entry_refused_before_writing(tmp_project):
    before = tmp_project.changelog_path.read_text()
    with pytest.raises(rules.RuleViolation) as e:
        writer.add_changelog_entry(tmp_project, title="Fix `thing` in config.js", why=None)
    assert tmp_project.changelog_path.read_text() == before
    fields = {p.field for p in e.value.problems}
    assert fields == {"title", "why"}


def test_backlog_item_refused_before_writing(tmp_project):
    before = tmp_project.backlog_path.read_text()
    with pytest.raises(rules.RuleViolation):
        writer.add_backlog_item(tmp_project, text=" ".join(["word"] * 30))
    assert tmp_project.backlog_path.read_text() == before


def test_backlog_item_with_note_is_written(tmp_project):
    writer.add_backlog_item(tmp_project, text="Link the feedback form", horizon="Now",
                            note="The URL goes in `frontend/src/config.js`.")
    assert "  The URL goes in `frontend/src/config.js`.\n" in tmp_project.backlog_path.read_text()


def test_multiline_why_cannot_inject_a_date_header(tmp_project):
    """A Why with line breaks used to write `## 2020-01-01` as a real header,
    re-dating every entry below it."""
    from ledger.parse import parse_changelog
    before = [(e.date, e.title) for e in parse_changelog(tmp_project.changelog_path)]
    writer.add_changelog_entry(tmp_project, "It is fixed",
                               "It is fixed now.\n## 2020-01-01\n### Fake entry")
    text = tmp_project.changelog_path.read_text()
    assert "**Why:** It is fixed now. ## 2020-01-01 ### Fake entry\n" in text
    assert "\n## 2020-01-01" not in text and "\n### Fake entry" not in text
    after = [(e.date, e.title) for e in parse_changelog(tmp_project.changelog_path)]
    assert after[1:] == before                      # older entries keep their dates


def test_why_from_a_web_form_leaves_no_carriage_returns(tmp_project):
    writer.add_changelog_entry(tmp_project, "Forms save cleanly",
                               "Browsers send Windows line breaks.\r\nNow they are gone.")
    raw = tmp_project.changelog_path.read_bytes()
    assert b"\r" not in raw
    assert b"**Why:** Browsers send Windows line breaks. Now they are gone.\n" in raw


def test_title_with_bare_carriage_return_is_refused(tmp_project):
    before = tmp_project.changelog_path.read_text()
    with pytest.raises(rules.RuleViolation) as e:
        writer.add_changelog_entry(tmp_project, "First part\rsecond part", WHY)
    assert "one line" in str(e.value)
    assert tmp_project.changelog_path.read_text() == before


def test_backlog_item_with_bad_tag_is_refused(tmp_project):
    before = tmp_project.backlog_path.read_text()
    with pytest.raises(rules.RuleViolation) as e:
        writer.add_backlog_item(tmp_project, "Fix the footer", tag="two words")
    assert e.value.problems[0].field == "tag"
    assert tmp_project.backlog_path.read_text() == before
