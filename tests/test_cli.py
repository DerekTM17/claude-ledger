import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ledger.cli import app

WHY = "It helps people find things faster."


@pytest.fixture
def runner():
    return CliRunner()


def _init_project(root: Path, slug: str, with_files: bool = True) -> Path:
    p = root / slug
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    if with_files:
        (p / "docs").mkdir()
        (p / "docs" / "CHANGELOG.md").write_text(
            "# X — Changelog\n\nIntro.\n\n## 2026-05-18\n\n### Today\n"
        )
        (p / "docs" / "BACKLOG.md").write_text(
            "# X — Backlog\n\n## Now\n- [ ] one\n\n## Soon\n\n## Someday\n"
        )
    return p


def test_status_lists_projects(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    _init_project(proj_root, "alpha")
    _init_project(proj_root, "beta")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "alpha" in result.stdout
    assert "beta" in result.stdout


def test_status_json_emits_machine_readable(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    _init_project(proj_root, "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0
    import json
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data[0]["slug"] == "alpha"


def test_idea_appends_to_default_soon(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["idea", "alpha", "do the thing"])
    assert result.exit_code == 0
    content = (proj / "docs" / "BACKLOG.md").read_text()
    assert "do the thing" in content
    soon_idx = content.index("## Soon")
    someday_idx = content.index("## Someday")
    new_idx = content.index("do the thing")
    assert soon_idx < new_idx < someday_idx


def test_idea_now_flag(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["idea", "alpha", "--now", "--tag", "bug", "fix x"])
    assert result.exit_code == 0
    content = (proj / "docs" / "BACKLOG.md").read_text()
    assert "**[bug]** fix x" in content
    new_idx = content.index("fix x")
    soon_idx = content.index("## Soon")
    assert new_idx < soon_idx


def test_idea_typo_suggests_closest(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "trackforge")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["idea", "trackforg", "x"])
    assert result.exit_code != 0
    assert "trackforge" in result.stderr.lower()


def test_idea_unknown_project_no_close_match(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["idea", "zzzzz", "x"])
    assert result.exit_code != 0
    assert "no project" in result.stderr.lower()


def test_ship_with_title_appends_to_today(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["ship", "alpha", "shipped thing", "--why", WHY])
    assert result.exit_code == 0
    content = (proj / "docs" / "CHANGELOG.md").read_text()
    assert "### shipped thing" in content


def test_ship_with_why(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    result = runner.invoke(app, ["ship", "alpha", "thing", "--why", "because z"])
    assert result.exit_code == 0
    content = (proj / "docs" / "CHANGELOG.md").read_text()
    assert "**Why:** because z" in content


def test_ship_lazy_creates_changelog(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha", with_files=False)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    assert not (proj / "docs" / "CHANGELOG.md").exists()
    result = runner.invoke(app, ["ship", "alpha", "first", "--why", WHY])
    assert result.exit_code == 0
    assert (proj / "docs" / "CHANGELOG.md").exists()


def test_edit_invokes_editor_with_backlog_path(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    log_file = tmp_path / "editor_invocation.txt"
    fake_editor = tmp_path / "fake-editor.sh"
    fake_editor.write_text(f'#!/bin/sh\necho "$1" > "{log_file}"\n')
    fake_editor.chmod(0o755)
    # edit uses os.execvp which replaces the process; use subprocess to test
    proc = subprocess.run(
        [sys.executable, "-m", "ledger", "edit", "alpha"],
        capture_output=True, text=True,
        env={**os.environ, "LEDGER_PROJECTS_ROOT": str(tmp_path / "projects"),
             "EDITOR": str(fake_editor)},
    )
    assert proc.returncode == 0
    assert (proj / "docs" / "BACKLOG.md").as_posix() in log_file.read_text()


def test_edit_log_flag_opens_changelog(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    log_file = tmp_path / "log_invocation.txt"
    fake_editor = tmp_path / "fake.sh"
    fake_editor.write_text(f'#!/bin/sh\necho "$1" > "{log_file}"\n')
    fake_editor.chmod(0o755)
    proc = subprocess.run(
        [sys.executable, "-m", "ledger", "edit", "alpha", "--log"],
        capture_output=True, text=True,
        env={**os.environ, "LEDGER_PROJECTS_ROOT": str(tmp_path / "projects"),
             "EDITOR": str(fake_editor)},
    )
    assert proc.returncode == 0
    assert (proj / "docs" / "CHANGELOG.md").as_posix() in log_file.read_text()


def test_search_finds_terms_across_projects(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    p_a = _init_project(proj_root, "alpha")
    p_b = _init_project(proj_root, "beta")
    (p_a / "docs" / "BACKLOG.md").write_text(
        "# X\n\n## Now\n- [ ] alpha-needle thing\n\n## Soon\n\n## Someday\n"
    )
    (p_b / "docs" / "CHANGELOG.md").write_text(
        "# Y\n\n## 2026-05-01\n\n### beta-needle title\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    res = runner.invoke(app, ["search", "needle"])
    assert res.exit_code == 0
    assert "alpha-needle" in res.stdout
    assert "beta-needle" in res.stdout


def test_search_empty_query_errors(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    _init_project(proj_root, "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    res = runner.invoke(app, ["search", ""])
    assert res.exit_code != 0


def test_search_scope_to_project(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    p_a = _init_project(proj_root, "alpha")
    p_b = _init_project(proj_root, "beta")
    (p_a / "docs" / "BACKLOG.md").write_text("# X\n\n## Now\n- [ ] needle\n\n## Soon\n\n## Someday\n")
    (p_b / "docs" / "BACKLOG.md").write_text("# Y\n\n## Now\n- [ ] needle\n\n## Soon\n\n## Someday\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    res = runner.invoke(app, ["search", "needle", "--project", "alpha"])
    assert res.exit_code == 0
    assert "alpha" in res.stdout
    assert "beta" not in res.stdout


def test_serve_command_exists_with_help(runner):
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.stdout
    assert "--bind" in result.stdout


def test_idea_now_auto_commits(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=proj, check=True)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))

    result = runner.invoke(app, ["idea", "alpha", "auto commit test"])
    assert result.exit_code == 0

    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=proj,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert "docs(backlog)" in log


def test_ship_now_auto_commits(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=proj, check=True)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))

    result = runner.invoke(app, ["ship", "alpha", "Did the thing", "--why", WHY])
    assert result.exit_code == 0

    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=proj,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert "docs(changelog)" in log


def test_init_scaffolds_backlog_and_changelog(runner, tmp_path, monkeypatch):
    proj = tmp_path / "projects" / "alpha"
    proj.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))

    result = runner.invoke(app, ["init", "alpha"])
    assert result.exit_code == 0
    assert (proj / "docs" / "BACKLOG.md").exists()
    assert (proj / "docs" / "CHANGELOG.md").exists()
    assert "Backlog" in (proj / "docs" / "BACKLOG.md").read_text()
    assert "Changelog" in (proj / "docs" / "CHANGELOG.md").read_text()


def test_init_is_idempotent(runner, tmp_path, monkeypatch):
    proj = tmp_path / "projects" / "alpha"
    proj.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, check=True)
    (proj / "docs").mkdir()
    (proj / "docs" / "BACKLOG.md").write_text("# existing\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))

    result = runner.invoke(app, ["init", "alpha"])
    assert result.exit_code == 0
    # Existing file untouched
    assert (proj / "docs" / "BACKLOG.md").read_text() == "# existing\n"


import json as _json


def test_hook_session_start_emits_json_when_in_project(runner, tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    proj = _init_project(proj_root, "alpha")
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=proj, check=True)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    payload = _json.dumps({"cwd": str(proj), "source": "startup",
                           "session_id": "sid-1"})
    result = runner.invoke(app, ["hook", "session-start"], input=payload)
    assert result.exit_code == 0
    out = _json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "alpha" in out["hookSpecificOutput"]["additionalContext"]


def test_hook_session_start_silent_outside_project(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    payload = _json.dumps({"cwd": str(tmp_path), "source": "startup",
                           "session_id": "sid-1"})
    result = runner.invoke(app, ["hook", "session-start"], input=payload)
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_hook_exits_zero_on_broken_input(runner):
    result = runner.invoke(app, ["hook", "session-start"], input="not json")
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def _seeded_project(root: Path, slug: str) -> Path:
    proj = _init_project(root, slug)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=proj, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=proj, check=True)
    subprocess.run(["git", "add", "."], cwd=proj, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=proj, check=True)
    return proj


def _fake_editor(tmp_path: Path, body: str | None) -> Path:
    """An $EDITOR that overwrites the file with body, or leaves it untouched if None."""
    ed = tmp_path / "fake-editor.sh"
    if body is None:
        ed.write_text("#!/bin/sh\nexit 0\n")
    else:
        src = tmp_path / "editor-body.txt"
        src.write_text(body)
        ed.write_text(f'#!/bin/sh\ncat "{src}" > "$1"\n')
    ed.chmod(0o755)
    return ed


def test_bare_ship_aborts_when_editor_closed_unchanged(runner, tmp_path, monkeypatch):
    proj = _seeded_project(tmp_path / "projects", "alpha")
    before = (proj / "docs" / "CHANGELOG.md").read_text()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("EDITOR", str(_fake_editor(tmp_path, None)))
    result = runner.invoke(app, ["ship", "alpha"])
    assert result.exit_code != 0
    after = (proj / "docs" / "CHANGELOG.md").read_text()
    assert after == before
    assert "edit me" not in after


def test_bare_ship_uses_editor_title_and_why_and_commits(runner, tmp_path, monkeypatch):
    proj = _seeded_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("EDITOR", str(_fake_editor(
        tmp_path, "# a comment line\nEditor title\n\nBecause reasons.\nSecond line.\n")))
    result = runner.invoke(app, ["ship", "alpha"])
    assert result.exit_code == 0, result.output
    content = (proj / "docs" / "CHANGELOG.md").read_text()
    assert "### Editor title" in content
    # I1: the Why is written as one paragraph, whatever its line breaks.
    assert "**Why:** Because reasons. Second line.\n" in content
    assert "a comment line" not in content
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=proj,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert "docs(changelog)" in log


def test_bare_ship_editor_with_args(runner, tmp_path, monkeypatch):
    # EDITOR values like "code --wait" must be split, not run as one binary name.
    proj = _seeded_project(tmp_path / "projects", "alpha")
    ed = _fake_editor(tmp_path, f"Split title\n\n{WHY}\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("EDITOR", f"sh {ed}")
    result = runner.invoke(app, ["ship", "alpha"])
    assert result.exit_code == 0, result.output
    assert "### Split title" in (proj / "docs" / "CHANGELOG.md").read_text()


def _needles_project(root: Path) -> Path:
    """alpha with the same needle in BACKLOG and CHANGELOG, tagged by file."""
    p = _init_project(root, "alpha")
    (p / "docs" / "BACKLOG.md").write_text(
        "# X\n\n## Now\n- [ ] needle-in-bag\n\n## Soon\n\n## Someday\n")
    (p / "docs" / "CHANGELOG.md").write_text(
        "# X\n\n## 2026-05-01\n\n### needle-in-log\n")
    return p


def test_search_log_flag_scopes_to_changelog(runner, tmp_path, monkeypatch):
    _needles_project(tmp_path / "projects")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["search", "needle", "--log"])
    assert res.exit_code == 0
    assert "needle-in-log" in res.stdout
    assert "needle-in-bag" not in res.stdout


def test_search_bag_flag_scopes_to_backlog(runner, tmp_path, monkeypatch):
    _needles_project(tmp_path / "projects")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["search", "needle", "--bag"])
    assert res.exit_code == 0
    assert "needle-in-bag" in res.stdout
    assert "needle-in-log" not in res.stdout


def test_edit_memory_flag_opens_memory_file(runner, tmp_path, monkeypatch):
    # Dashed slug: the memory filename uses underscores (project_alpha_beta.md).
    _init_project(tmp_path / "projects", "alpha-beta")
    log_file = tmp_path / "mem_invocation.txt"
    fake_editor = tmp_path / "fake.sh"
    fake_editor.write_text(f'#!/bin/sh\necho "$1" > "{log_file}"\n')
    fake_editor.chmod(0o755)
    proc = subprocess.run(
        [sys.executable, "-m", "ledger", "edit", "alpha-beta", "--memory"],
        capture_output=True, text=True,
        env={**os.environ, "LEDGER_PROJECTS_ROOT": str(tmp_path / "projects"),
             "EDITOR": str(fake_editor)},
    )
    assert proc.returncode == 0, proc.stderr
    assert log_file.read_text().strip().endswith("/project_alpha_beta.md")


def test_edit_log_and_memory_are_mutually_exclusive(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["edit", "alpha", "--log", "--memory"])
    assert res.exit_code == 2


def test_status_shows_next_up_and_accurate_counts(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "BACKLOG.md").write_text(
        "# X — Backlog\n\n## Now\n- [ ] **[feat]** do the next thing\n- [x] done thing\n\n"
        "## Soon\n- [ ] later thing\n\n## Someday\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("COLUMNS", "200")
    res = runner.invoke(app, ["status"])
    assert res.exit_code == 0
    assert "do the next thing" in res.stdout
    assert "CLAUDE MEMORY" not in res.stdout
    import re
    row = next(l for l in res.stdout.splitlines() if "alpha" in l)
    # NOW column shows 1: the done item is not counted.
    assert re.search(r"│\s+1\s+│\s+1\s+│", row), row


def test_status_json_has_next_up(runner, tmp_path, monkeypatch):
    import json
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["status", "--json"])
    data = json.loads(res.stdout)
    assert data[0]["next_up"] == "one"
    assert data[0]["backlog"] == {"now": 1, "soon": 0, "someday": 0}


def test_status_readable_at_columns_80(runner, tmp_path, monkeypatch):
    """Regression: at a narrow terminal, Rich's last-resort width collapse
    used to squeeze PROJECT/NOW/LATER to zero width once the two text
    columns' fixed max_width forced the row past the terminal width."""
    import re
    slug = "state-legislature-dashboard"
    proj = _init_project(tmp_path / "projects", slug)
    now_items = "".join(f"- [ ] now item {i}\n" for i in range(12))
    later_items = "".join(f"- [ ] later item {i}\n" for i in range(100))
    (proj / "docs" / "BACKLOG.md").write_text(
        f"# X — Backlog\n\n## Now\n{now_items}\n## Soon\n{later_items}\n## Someday\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("COLUMNS", "80")
    res = runner.invoke(app, ["status"])
    assert res.exit_code == 0
    row = next(l for l in res.stdout.splitlines() if slug in l)
    assert slug in row  # full slug visible, not truncated
    assert re.search(r"│\s*12\s*│\s*100\s*│", row), row


def test_status_memory_column_readable_at_columns_80(runner, tmp_path, monkeypatch):
    """--memory adds a fixed-max_width column too; it must share space via
    ratio like LAST FINISHED/NEXT UP, not starve PROJECT/NOW/LATER to 0."""
    import re
    slug = "state-legislature-dashboard"
    proj = _init_project(tmp_path / "projects", slug)
    now_items = "".join(f"- [ ] now item {i}\n" for i in range(12))
    later_items = "".join(f"- [ ] later item {i}\n" for i in range(100))
    (proj / "docs" / "BACKLOG.md").write_text(
        f"# X — Backlog\n\n## Now\n{now_items}\n## Soon\n{later_items}\n## Someday\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("COLUMNS", "80")
    res = runner.invoke(app, ["status", "--memory"])
    assert res.exit_code == 0
    row = next(l for l in res.stdout.splitlines() if slug in l)
    assert slug in row
    assert re.search(r"│\s*12\s*│\s*100\s*│", row), row


def test_ship_refuses_rule_breaking_entry(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    before = (proj / "docs" / "CHANGELOG.md").read_text()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["ship", "alpha", "Merged PR #92"])
    assert res.exit_code == 1
    assert "PR #92" in res.output and "Why: it's empty" in res.output
    assert "ledger rules" in res.output
    assert (proj / "docs" / "CHANGELOG.md").read_text() == before


def test_idea_note_flag(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["idea", "alpha", "Link the feedback form", "--note", "See `config.js`."])
    assert res.exit_code == 0, res.output
    assert "  See `config.js`.\n" in (proj / "docs" / "BACKLOG.md").read_text()


def test_idea_output_keeps_tag_brackets(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["idea", "alpha", " ".join(["word"] * 30), "--tag", "feat"])
    assert res.exit_code == 1
    assert "30 words" in res.output


def test_rules_command_prints_rules(runner):
    from ledger.rules import RULES_TEXT
    res = runner.invoke(app, ["rules"])
    assert res.exit_code == 0
    assert res.output.strip() == RULES_TEXT.strip()


def test_check_reports_recent_entries_and_now_items(runner, tmp_path, monkeypatch):
    from datetime import date
    proj = _init_project(tmp_path / "projects", "alpha")
    today = date.today().isoformat()
    (proj / "docs" / "CHANGELOG.md").write_text(
        f"# alpha — Changelog\n\n## {today}\n\n### Merged PR #92\n\n**Why:** It helps.\n\n"
        "## 2020-01-01\n\n### Old `code` title\n\n**Why:** Old and ignored.\n"
    )
    (proj / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n- [ ] Paste the URL into config.js\n"
        "- [ ] Fine headline\n  A long note " + "w " * 100 + "\n\n"
        "## Soon\n- [ ] Soon items with `code` are not checked\n\n## Someday\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["check", "alpha"])
    assert res.exit_code == 1
    assert "PR #92" in res.output
    assert "config.js" in res.output
    assert "Old" not in res.output             # outside --since
    assert "Soon items" not in res.output      # only Now items are checked
    assert "Note:" not in res.output           # existing notes are not length-checked
    assert "2 need rewriting" in res.output


def test_check_passes_clean_project(runner, tmp_path, monkeypatch):
    from datetime import date
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "CHANGELOG.md").write_text(
        f"# alpha — Changelog\n\n## {date.today().isoformat()}\n\n"
        "### Sessions can no longer overwrite each other's records\n\n"
        "**Why:** Two sessions saving at once could erase each other's notes. Now they take turns.\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["check", "alpha"])
    assert res.exit_code == 0, res.output
    assert "follows the rules" in res.output


def test_done_command(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["done", "alpha", "one"])
    assert res.exit_code == 0, res.output
    assert "Done list" in res.output
    assert (proj / "docs" / "BACKLOG-DONE.md").exists()


def test_done_command_no_match(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["done", "alpha", "nothing like this"])
    assert res.exit_code == 1
    assert "No open item" in res.output


def test_tidy_all_skips(runner, tmp_path, monkeypatch):
    root = tmp_path / "projects"
    a = _init_project(root, "alpha")
    b = _init_project(root, "beta")
    for p in (a, b):
        (p / "docs" / "BACKLOG.md").write_text("# X — Backlog\n\n## Now\n- [x] finished\n\n## Soon\n\n## Someday\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(root))
    res = runner.invoke(app, ["tidy", "--all", "--skip", "beta"])
    assert res.exit_code == 0, res.output
    assert (a / "docs" / "BACKLOG-DONE.md").exists()
    assert not (b / "docs" / "BACKLOG-DONE.md").exists()


def test_search_includes_done_list(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "BACKLOG-DONE.md").write_text("# X — Done\n\n## 2026-09-17\n\n- [x] archived-needle item\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["search", "archived-needle"])
    assert "archived-needle" in res.stdout


def test_status_and_greeting_agree_with_dashboard_on_last_finished(runner, tmp_path, monkeypatch):
    """status, the session greeting and the dashboard all pick the newest
    entry, even under a `## <date> (later)` header."""
    import json
    from datetime import date
    from ledger import hooks, views
    from ledger.models import Project
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "CHANGELOG.md").write_text(
        "# alpha — Changelog\n\n"
        "## 2026-09-10 (later)\n\n### Later same-day fix\n\n**Why:** It came late.\n\n"
        "## 2026-09-10\n\n### Morning work\n\n**Why:** It came early.\n"
    )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    project = Project(slug="alpha", path=proj)
    board = views.dashboard([project], date(2026, 9, 17))["rows"][0]
    assert "Later same-day fix" in board["last_title"]
    data = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert data[0]["last_shipped_title"] == "Later same-day fix"
    greeting = hooks._build_summary(project, 0, False, None)
    assert "Later same-day fix" in greeting and "Morning work" not in greeting


def test_done_hint_prints_text_without_backslash(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["done", "alpha", "[bug] footer"])
    assert res.exit_code == 1
    assert 'ledger search "[bug] footer"' in res.output
    assert "\\[" not in res.output


def test_done_with_blank_text_moves_nothing(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    before = (proj / "docs" / "BACKLOG.md").read_text()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["done", "alpha", "   "])
    assert res.exit_code != 0
    assert "words from" in res.output
    assert (proj / "docs" / "BACKLOG.md").read_text() == before
    assert not (proj / "docs" / "BACKLOG-DONE.md").exists()


def test_done_reports_a_backlog_that_changed_meanwhile(runner, tmp_path, monkeypatch):
    from ledger import archive
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))

    def changed(*a, **k):
        raise archive.BacklogChanged()

    monkeypatch.setattr(archive, "move_items", changed)
    res = runner.invoke(app, ["done", "alpha", "one"])
    assert res.exit_code == 1
    assert "changed while ledger was working" in res.output
    assert "Traceback" not in res.output


def test_idea_success_message_keeps_tag(runner, tmp_path, monkeypatch):
    _init_project(tmp_path / "projects", "alpha")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("COLUMNS", "200")    # keep the message on one line
    res = runner.invoke(app, ["idea", "alpha", "Fix the footer", "--tag", "bug"])
    assert res.exit_code == 0, res.output
    assert "(Soon, [bug])" in res.output


def test_idea_refuses_a_tag_that_isnt_one_short_word(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    before = (proj / "docs" / "BACKLOG.md").read_text()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["idea", "alpha", "Fix the footer", "--tag", "two words"])
    assert res.exit_code == 1
    assert "Tag:" in res.output
    assert (proj / "docs" / "BACKLOG.md").read_text() == before


def test_search_output_keeps_brackets(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "BACKLOG-DONE.md").write_text(
        "# X — Done\n\n## 2026-09-17\n\n- [x] **[bug]** footer-needle [red]fixed[/red]\n")
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("COLUMNS", "200")
    res = runner.invoke(app, ["search", "footer-needle"])
    assert res.exit_code == 0, res.output
    assert "- [x] **[bug]** footer-needle [red]fixed[/red]" in res.stdout


def test_tidy_reports_a_skipped_commit(runner, tmp_path, monkeypatch):
    proj = _init_project(tmp_path / "projects", "alpha")
    (proj / "docs" / "BACKLOG.md").write_text("# X — Backlog\n\n## Now\n- [x] finished\n\n## Soon\n\n## Someday\n")
    (proj / ".git" / "rebase-merge").mkdir()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    res = runner.invoke(app, ["tidy", "alpha"])
    assert res.exit_code == 0, res.output
    assert "moved 1 finished item" in res.output
    assert "commit skipped: mid-rebase" in res.output


def test_status_json_always_has_memory(runner, tmp_path, monkeypatch):
    """--memory controls the table column only; JSON readers always get the text."""
    import json
    from ledger.memory import claude_slug
    _init_project(tmp_path / "projects", "alpha")
    mem = tmp_path / ".claude" / "projects" / claude_slug(tmp_path) / "memory"
    mem.mkdir(parents=True)
    (mem / "project_alpha.md").write_text('---\ndescription: "Alpha note."\n---\n')
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.delenv("LEDGER_NO_MEMORY", raising=False)
    data = json.loads(runner.invoke(app, ["status", "--json"]).stdout)
    assert data[0]["memory"] == "Alpha note."
    table = runner.invoke(app, ["status"]).stdout
    assert "Alpha note." not in table and "MEMORY" not in table
