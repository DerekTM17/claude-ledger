import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ledger import hooks


@pytest.fixture
def projects_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    return root


def _make_project(root: Path, slug: str, with_docs: bool = True) -> Path:
    p = root / slug
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=p, check=True)
    (p / "README.md").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=p, check=True)
    if with_docs:
        (p / "docs").mkdir()
        (p / "docs" / "BACKLOG.md").write_text(
            "# alpha — Backlog\n\n## Now\n- [ ] one\n\n## Soon\n\n## Someday\n"
        )
        (p / "docs" / "CHANGELOG.md").write_text(
            "# alpha — Changelog\n\n## 2026-05-20\n\n### Did a thing\n"
        )
    return p


def test_session_start_non_project_returns_none(projects_root: Path, tmp_path: Path):
    payload = {"cwd": str(tmp_path / "somewhere-else"),
               "source": "startup", "session_id": "sid-1"}
    assert hooks.session_start(payload) is None


def test_session_start_untracked_project_nudges_to_init(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=False)
    payload = {"cwd": str(projects_root / "alpha"),
               "source": "startup", "session_id": "sid-1"}
    out = hooks.session_start(payload)
    assert out is not None
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "ledger init alpha" in text


def test_session_start_summary_includes_counts_and_recent_ship(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=True)
    payload = {"cwd": str(projects_root / "alpha"),
               "source": "startup", "session_id": "sid-1"}
    out = hooks.session_start(payload)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "alpha" in text
    assert "1 to do now" in text
    assert "Did a thing" in text


def test_session_start_counts_items_added_since_last_visit(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    # Seed an "old" last_seen so any item added today counts as new
    from ledger import state
    s = state.load_state()
    state.get_project(s, "alpha")["last_seen_at"] = "2020-01-01T00:00:00+00:00"
    state.save_state(s)
    # Add an item with today's added-comment
    (p / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n- [ ] one <!-- added 2026-05-28 -->\n\n## Soon\n\n## Someday\n"
    )
    payload = {"cwd": str(p), "source": "startup", "session_id": "sid-2"}
    out = hooks.session_start(payload)
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "1 added since your last visit" in text


def test_session_start_emits_greeting_only_on_startup(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=True)
    cwd = str(projects_root / "alpha")
    sup = hooks.session_start({"cwd": cwd, "source": "startup", "session_id": "s1"})
    res = hooks.session_start({"cwd": cwd, "source": "resume", "session_id": "s1"})
    assert "Open this reply" in sup["hookSpecificOutput"]["additionalContext"]
    assert "Open this reply" not in res["hookSpecificOutput"]["additionalContext"]
    assert "Background context" in res["hookSpecificOutput"]["additionalContext"]


def test_session_start_includes_capture_instruction(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=True)
    out = hooks.session_start({"cwd": str(projects_root / "alpha"),
                               "source": "startup", "session_id": "s1"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "ledger ship" in text  # capture instruction present


def test_greeting_is_plain(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=True)
    out = hooks.session_start({"cwd": str(projects_root / "alpha"), "source": "startup", "session_id": "s"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "📋 Ledger · alpha: 1 to do now, 0 later" in text
    assert "last finished" in text
    assert "ledger rules" in text
    assert "ledger done" in text


def test_greeting_never_shows_half_a_link(projects_root: Path):
    """plain() must run before the clamp, or a cut link shows as '[the…'."""
    p = _make_project(projects_root, "alpha", with_docs=True)
    # The link starts just before the 70-character cut, so it gets split.
    long = "Made " + "x" * 55 + " [the linked page](https://example.com/x) better"
    (p / "docs" / "CHANGELOG.md").write_text(
        f"# alpha — Changelog\n\n## 2026-05-20\n\n### {long}\n")
    out = hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "s"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "[the" not in text and "](" not in text


def test_orphan_note_wording(projects_root: Path):
    # Reuse the two-orphan setup from test_orphan_note_aggregates_all_orphans_and_dedupes_commits.
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import state
    seed = _head(p)
    _commit(p, "c1")
    s = state.load_state()
    state.add_open_session(s, "alpha", "sid-a", _recent(), seed)
    state.save_state(s)
    out = hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "now"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert '⚠️ 1 earlier session ended without a changelog entry (1 commit since). Say "capture the missed sessions".' in text


def test_session_start_records_open_marker(projects_root: Path):
    _make_project(projects_root, "alpha", with_docs=True)
    hooks.session_start({"cwd": str(projects_root / "alpha"),
                         "source": "startup", "session_id": "sid-new"})
    from ledger import state
    s = state.load_state()
    sessions = s["projects"]["alpha"]["open_sessions"]
    assert "sid-new" in sessions
    assert sessions["sid-new"]["start_head"] is not None


def test_session_start_detects_orphan_with_commits_since(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    # Plant an open marker from a "previous" session at the seed commit.
    seed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=p,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    from ledger import state
    s = state.load_state()
    # Use a recent, relative timestamp: a hardcoded date eventually ages past
    # the 30-day open-session GC window (_gc_open_sessions) and the marker gets
    # dropped before the orphan detector runs, making this test time-bomb fail.
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    state.add_open_session(s, "alpha", "sid-prev", recent, seed)
    state.save_state(s)
    # Make a commit (simulates work done in the orphaned session)
    (p / "newfile.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "work"], cwd=p, check=True)

    out = hooks.session_start({"cwd": str(p), "source": "startup",
                               "session_id": "sid-current"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "ended without a changelog entry" in text
    assert "1 commit" in text


def test_session_start_commits_dangling_sessions_md(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    # Simulate a SessionEnd having written an uncommitted SESSIONS.md
    (p / "docs" / "SESSIONS.md").write_text("# alpha — Sessions\n\nstub here\n")
    from ledger import state
    s = state.load_state()
    state.get_project(s, "alpha")["stub_pending"] = True
    state.save_state(s)

    hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-new"})

    # SESSIONS.md is now committed
    status = subprocess.run(
        ["git", "status", "--porcelain", "docs/SESSIONS.md"],
        cwd=p, capture_output=True, text=True, check=True,
    ).stdout
    assert status.strip() == ""  # clean
    # stub_pending cleared
    s2 = state.load_state()
    assert s2["projects"]["alpha"]["stub_pending"] is False


def test_session_start_returns_none_on_any_broken_input(projects_root: Path):
    # Garbage cwd, missing keys, weird types — every shape exits cleanly.
    assert hooks.session_start({}) is None
    assert hooks.session_start({"cwd": "/no/such/path/xyz", "source": "startup"}) is None
    assert hooks.session_start({"cwd": 12345, "source": "startup"}) is None  # type: ignore[arg-type]


def test_session_start_returns_none_when_state_file_corrupt(projects_root: Path, tmp_path: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    # Write garbage where state.json lives
    state_path = Path(os.environ["LEDGER_STATE_PATH"])
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{ broken")
    # state.load_state recovers to empty, so this should still succeed (not None)
    out = hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "s"})
    assert out is not None  # corrupt state ≠ session-breaking


def test_session_end_appends_stub_and_clears_marker(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    # Open a marker first via session_start
    hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-x"})
    # Do work: a commit
    (p / "newfile.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feat: x"], cwd=p, check=True)

    hooks.session_end({"cwd": str(p), "session_id": "sid-x",
                       "transcript_path": "", "reason": "logout"})

    # Stub appended
    sessions = (p / "docs" / "SESSIONS.md").read_text(encoding="utf-8")
    assert "sid-x" in sessions  # full id (first 8 chars) is in heading
    assert "feat: x" in sessions
    # Marker cleared, stub_pending set
    from ledger import state
    s = state.load_state()
    assert "sid-x" not in s["projects"]["alpha"]["open_sessions"]
    assert s["projects"]["alpha"]["stub_pending"] is True


def test_session_end_no_op_when_no_work_done(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-y"})
    # No new commits.
    hooks.session_end({"cwd": str(p), "session_id": "sid-y",
                       "transcript_path": "", "reason": "logout"})
    # No SESSIONS.md should be created when there's nothing to capture.
    assert not (p / "docs" / "SESSIONS.md").exists()
    from ledger import state
    s = state.load_state()
    assert s["projects"]["alpha"]["stub_pending"] is False


def test_session_end_non_project_is_silent(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    # Should simply return None without raising
    assert hooks.session_end({"cwd": str(tmp_path), "session_id": "x"}) is None


def test_session_start_instruction_includes_idea_for_backlog_edits(projects_root: Path):
    """Regression: smoke test 2026-06-01 showed Claude direct-editing BACKLOG.md
    instead of using `ledger idea` because the injected instruction only
    mentioned `ledger ship`. The instruction must teach both verbs.
    """
    _make_project(projects_root, "alpha", with_docs=True)
    out = hooks.session_start({"cwd": str(projects_root / "alpha"),
                               "source": "startup", "session_id": "s1"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "ledger idea" in text
    assert "Never edit" in text


def test_last_user_message_handles_string_content(tmp_path: Path):
    """Real Claude Code transcript: message.content is a str."""
    from ledger.hooks import _last_user_message
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","userType":"external","message":{"role":"user","content":"first prompt"}}\n'
        '{"type":"user","userType":"external","message":{"role":"user","content":"last prompt"}}\n'
    )
    assert _last_user_message(str(p)) == "last prompt"


def test_last_user_message_handles_list_content(tmp_path: Path):
    """message.content is a list of content blocks (text + tool_result)."""
    from ledger.hooks import _last_user_message
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","userType":"external","message":{"role":"user",'
        '"content":[{"type":"text","text":"hello there"},'
        '{"type":"tool_result","content":"noise"}]}}\n'
    )
    assert _last_user_message(str(p)) == "hello there"


def test_last_user_message_skips_internal_user_records(tmp_path: Path):
    """userType=internal is a synthetic tool-result wrapper, not a human prompt."""
    from ledger.hooks import _last_user_message
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","userType":"external","message":{"content":"the real prompt"}}\n'
        '{"type":"user","userType":"internal","message":{"content":[{"type":"tool_result","content":"junk"}]}}\n'
    )
    assert _last_user_message(str(p)) == "the real prompt"


def test_last_user_message_handles_missing_file(tmp_path: Path):
    from ledger.hooks import _last_user_message
    assert _last_user_message(str(tmp_path / "nope.jsonl")) is None


def test_last_user_message_handles_empty_and_malformed_lines(tmp_path: Path):
    """Mixed valid + garbage lines; valid records still extracted."""
    from ledger.hooks import _last_user_message
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","userType":"external","message":{"content":"good"}}\n'
        'not even json\n'
        '{"type":"assistant"}\n'
        '\n'
    )
    assert _last_user_message(str(p)) == "good"


def test_last_user_message_skips_slash_command_echoes(tmp_path: Path):
    """Claude Code logs `/exit` etc. as synthetic user records — skip them
    so the captured prompt is the last *typed* one, not '<local-command-stdout>…'.
    """
    from ledger.hooks import _last_user_message
    p = tmp_path / "t.jsonl"
    p.write_text(
        '{"type":"user","userType":"external","message":{"content":"real human prompt"}}\n'
        '{"type":"user","userType":"external","message":{"content":"<local-command-caveat>Caveat: blah</local-command-caveat>"}}\n'
        '{"type":"user","userType":"external","message":{"content":"<command-name>/exit</command-name>"}}\n'
        '{"type":"user","userType":"external","message":{"content":"<local-command-stdout>Catch you later!</local-command-stdout>"}}\n'
    )
    assert _last_user_message(str(p)) == "real human prompt"


# --- multi-orphan handling ------------------------------------------------

def _head(p: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=p,
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(p: Path, name: str) -> None:
    (p / name).write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(["git", "commit", "-q", "-m", name], cwd=p, check=True)


def _recent() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")


def test_orphan_note_aggregates_all_orphans_and_dedupes_commits(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import state
    seed = _head(p)
    _commit(p, "c1")
    mid = _head(p)
    _commit(p, "c2")
    s = state.load_state()
    state.add_open_session(s, "alpha", "sid-a", _recent(), seed)  # saw c1+c2
    state.add_open_session(s, "alpha", "sid-b", _recent(), mid)   # saw c2 (overlap)
    state.save_state(s)

    out = hooks.session_start({"cwd": str(p), "source": "startup",
                               "session_id": "sid-current"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "2 earlier sessions ended without a changelog entry" in text
    assert "(2 commits since)" in text  # c1, c2 counted once each


def test_orphan_note_skips_sessions_whose_process_is_alive(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import liveness, state
    seed = _head(p)
    _commit(p, "c1")
    me = os.getpid()
    s = state.load_state()
    # Another window still open in this project: its process is running.
    state.add_open_session(s, "alpha", "sid-live", _recent(), seed,
                           pid=me, pid_start=liveness.proc_start_time(me))
    state.save_state(s)

    out = hooks.session_start({"cwd": str(p), "source": "startup",
                               "session_id": "sid-current"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "ended without a changelog entry" not in text


def test_reused_pid_is_not_mistaken_for_live_session(projects_root: Path):
    from ledger import liveness
    me = os.getpid()
    assert liveness.is_alive({"pid": me, "pid_start": liveness.proc_start_time(me)})
    assert not liveness.is_alive({"pid": me, "pid_start": "not-the-real-start"})
    assert not liveness.is_alive({})  # pre-upgrade markers carry no pid


def test_session_start_records_harness_pid(projects_root: Path, monkeypatch):
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import liveness, state
    monkeypatch.setattr(liveness, "harness_process", lambda: (4242, "777"))
    hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-1"})
    marker = state.load_state()["projects"]["alpha"]["open_sessions"]["sid-1"]
    assert marker["pid"] == 4242 and marker["pid_start"] == "777"


def test_session_start_drops_dead_markers_that_did_no_work(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import state
    s = state.load_state()
    state.add_open_session(s, "alpha", "sid-idle", _recent(), _head(p))
    state.save_state(s)
    hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-2"})
    assert "sid-idle" not in state.load_state()["projects"]["alpha"]["open_sessions"]


def test_ship_clears_dead_orphans_but_keeps_live_sessions(projects_root: Path):
    p = _make_project(projects_root, "alpha", with_docs=True)
    from ledger import liveness, state, writer
    from ledger.models import Project
    seed = _head(p)
    _commit(p, "c1")
    me = os.getpid()
    s = state.load_state()
    state.add_open_session(s, "alpha", "sid-dead", _recent(), seed)
    state.add_open_session(s, "alpha", "sid-live", _recent(), seed,
                           pid=me, pid_start=liveness.proc_start_time(me))
    state.save_state(s)

    writer.add_changelog_entry(Project(slug="alpha", path=p), title="Recorded it",
                               why="It helps people find things faster.")

    sessions = state.load_state()["projects"]["alpha"]["open_sessions"]
    assert "sid-dead" not in sessions
    assert "sid-live" in sessions
    out = hooks.session_start({"cwd": str(p), "source": "startup", "session_id": "sid-3"})
    assert "ended without a changelog entry" not in out["hookSpecificOutput"]["additionalContext"]


# --- Sessions started above the projects (e.g. the home folder) ---


def test_session_start_above_projects_summarises_all(projects_root: Path):
    _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    _make_project(projects_root, "gamma", with_docs=False)  # untracked: left out
    out = hooks.session_start({"cwd": str(projects_root.parent),
                               "source": "startup", "session_id": "sid-h"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "📋 Ledger · 2 projects, 2 to do now" in text
    assert "alpha (" in text and "beta (" in text
    assert "gamma" not in text
    from ledger import state
    s = state.load_state()
    assert "sid-h" in s["projects"]["alpha"]["open_sessions"]
    assert "sid-h" in s["projects"]["beta"]["open_sessions"]


def test_session_end_above_projects_stubs_only_projects_with_work(projects_root: Path):
    a = _make_project(projects_root, "alpha")
    b = _make_project(projects_root, "beta")
    home = projects_root.parent
    hooks.session_start({"cwd": str(home), "source": "startup", "session_id": "sid-h"})
    _commit(a, "feat-a")
    hooks.session_end({"cwd": str(home), "session_id": "sid-h", "transcript_path": ""})
    assert "feat-a" in (a / "docs" / "SESSIONS.md").read_text(encoding="utf-8")
    assert not (b / "docs" / "SESSIONS.md").exists()
    from ledger import state
    s = state.load_state()
    assert s["projects"]["alpha"]["stub_pending"] is True
    assert "sid-h" not in s["projects"]["alpha"]["open_sessions"]
    assert "sid-h" not in s["projects"]["beta"]["open_sessions"]


def test_session_start_above_projects_names_project_with_orphan(projects_root: Path):
    a = _make_project(projects_root, "alpha")
    _make_project(projects_root, "beta")
    from ledger import state
    with state.locked_state() as st:
        state.add_open_session(st, "alpha", "dead", _recent(), _head(a))
    _commit(a, "lost-work")
    out = hooks.session_start({"cwd": str(projects_root.parent),
                               "source": "startup", "session_id": "sid-h"})
    text = out["hookSpecificOutput"]["additionalContext"]
    assert "alpha: ⚠️ 1 earlier session ended without a changelog entry" in text
    assert "beta: ⚠️" not in text


def test_session_start_above_projects_commits_pending_stub(projects_root: Path):
    a = _make_project(projects_root, "alpha")
    hooks.session_start({"cwd": str(a), "source": "startup", "session_id": "s1"})
    _commit(a, "work")
    hooks.session_end({"cwd": str(a), "session_id": "s1", "transcript_path": ""})
    hooks.session_start({"cwd": str(projects_root.parent),
                         "source": "startup", "session_id": "s2"})
    status = subprocess.run(["git", "status", "--porcelain"], cwd=a,
                            capture_output=True, text=True).stdout
    assert "SESSIONS.md" not in status
