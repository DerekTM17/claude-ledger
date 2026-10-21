import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from ledger.state import (
    STATE_VERSION, load_state, save_state, get_project,
    add_open_session, clear_open_session, locked_state,
)


def test_load_state_returns_empty_when_missing(tmp_path: Path):
    p = tmp_path / "state.json"
    data = load_state(p)
    assert data == {"version": STATE_VERSION, "projects": {}}


def test_save_and_load_round_trip(tmp_path: Path):
    p = tmp_path / "state.json"
    state = {"version": STATE_VERSION, "projects": {
        "alpha": {"last_seen_at": "2026-05-27T10:00:00", "last_seen_head": "abc",
                  "open_sessions": {}, "stub_pending": False},
    }}
    save_state(state, p)
    loaded = load_state(p)
    assert loaded["projects"]["alpha"]["last_seen_head"] == "abc"


def test_save_state_is_atomic(tmp_path: Path):
    """If state file already exists, it remains valid (no torn writes)."""
    p = tmp_path / "state.json"
    save_state({"version": STATE_VERSION, "projects": {}}, p)
    # No leftover tmp files in the dir
    leftovers = [f for f in p.parent.iterdir() if f.name.startswith("state.") and f.name.endswith(".tmp")]
    assert leftovers == []


def test_load_state_recovers_from_corrupt_json(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{ not json")
    data = load_state(p)
    assert data == {"version": STATE_VERSION, "projects": {}}


def test_load_state_recovers_from_wrong_version(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 999, "projects": {}}))
    data = load_state(p)
    assert data["version"] == STATE_VERSION


def test_add_and_clear_open_session(tmp_path: Path):
    state = load_state(tmp_path / "s.json")
    add_open_session(state, "alpha", "sid-1", "2026-05-27T10:00:00+00:00", "abc")
    assert state["projects"]["alpha"]["open_sessions"]["sid-1"]["start_head"] == "abc"
    clear_open_session(state, "alpha", "sid-1")
    assert "sid-1" not in state["projects"]["alpha"]["open_sessions"]


def test_load_state_gcs_stale_open_sessions(tmp_path: Path):
    p = tmp_path / "s.json"
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat(timespec="seconds")
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    save_state({"version": STATE_VERSION, "projects": {
        "alpha": {
            "last_seen_at": None, "last_seen_head": None, "stub_pending": False,
            "open_sessions": {
                "old": {"started_at": old, "start_head": "x"},
                "fresh": {"started_at": fresh, "start_head": "y"},
            },
        }
    }}, p)
    loaded = load_state(p)
    sessions = loaded["projects"]["alpha"]["open_sessions"]
    assert "old" not in sessions
    assert "fresh" in sessions


def _add_session_under_lock(args):
    """Worker for the concurrency test: one read-modify-write cycle."""
    path, i = args
    import time
    with locked_state(Path(path)) as st:
        # Widen the race window so an unlocked implementation reliably loses writes.
        time.sleep(0.01)
        add_open_session(st, "alpha", f"s{i}", "2099-01-01T00:00:00+00:00", None)


def test_locked_state_serializes_concurrent_writers(tmp_path: Path):
    import multiprocessing
    p = tmp_path / "state.json"
    n = 16
    with multiprocessing.get_context("fork").Pool(8) as pool:
        pool.map(_add_session_under_lock, [(str(p), i) for i in range(n)])
    sessions = load_state(p)["projects"]["alpha"]["open_sessions"]
    assert sorted(sessions) == sorted(f"s{i}" for i in range(n))


def test_locked_state_saves_on_clean_exit(tmp_path: Path):
    p = tmp_path / "state.json"
    with locked_state(p) as st:
        get_project(st, "alpha")["stub_pending"] = True
    assert load_state(p)["projects"]["alpha"]["stub_pending"] is True


def test_locked_state_discards_changes_on_exception(tmp_path: Path):
    p = tmp_path / "state.json"
    try:
        with locked_state(p) as st:
            get_project(st, "alpha")["stub_pending"] = True
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "alpha" not in load_state(p)["projects"]
