"""Per-project state for the ledger hooks (last_seen, open sessions, stub flag)."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ledger.config import default_state_path

STATE_VERSION = 1
OPEN_SESSION_MAX_AGE_DAYS = 30


def _path(path: Path | None) -> Path:
    if path is not None:
        return path
    env = os.environ.get("LEDGER_STATE_PATH")
    return Path(env) if env else default_state_path()


def _empty() -> dict[str, Any]:
    return {"version": STATE_VERSION, "projects": {}}


def load_state(path: Path | None = None) -> dict[str, Any]:
    p = _path(path)
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return _empty()
    return _gc_open_sessions(data)


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="state.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def locked_state(path: Path | None = None) -> Iterator[dict[str, Any]]:
    """Load state under an exclusive lock, yield it, save it on clean exit.

    Concurrent hooks (sessions in different projects or harnesses) each do a
    load-mutate-save cycle; without the lock, the last writer silently drops
    the others' changes (e.g. a stub_pending flag). The lock lives on a
    sidecar file because save_state() swaps state.json's inode via
    os.replace, which would orphan a lock held on the old inode. flock is
    released by the kernel if the holder dies, so a crash can't wedge it.
    On exception the mutations are discarded, not saved.
    """
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_name(p.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = load_state(p)
            yield state
            save_state(state, p)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def get_project(state: dict[str, Any], slug: str) -> dict[str, Any]:
    return state.setdefault("projects", {}).setdefault(slug, {
        "last_seen_at": None,
        "last_seen_head": None,
        "open_sessions": {},
        "stub_pending": False,
    })


def add_open_session(state: dict[str, Any], slug: str, session_id: str,
                     started_at: str, start_head: str | None,
                     pid: int | None = None, pid_start: str | None = None) -> None:
    proj = get_project(state, slug)
    marker: dict[str, Any] = {"started_at": started_at, "start_head": start_head}
    if pid and pid_start:
        # Lets liveness.is_alive() tell a still-open window from an orphan.
        marker["pid"], marker["pid_start"] = pid, pid_start
    proj["open_sessions"][session_id] = marker


def prune_dead_sessions(state: dict[str, Any], slug: str) -> None:
    """Drop open markers whose harness process is gone (see liveness)."""
    from ledger import liveness
    proj = state.get("projects", {}).get(slug)
    if not proj:
        return
    proj["open_sessions"] = {
        sid: info for sid, info in proj.get("open_sessions", {}).items()
        if liveness.is_alive(info)
    }


def clear_open_session(state: dict[str, Any], slug: str, session_id: str) -> None:
    proj = get_project(state, slug)
    proj["open_sessions"].pop(session_id, None)


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _gc_open_sessions(state: dict[str, Any]) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=OPEN_SESSION_MAX_AGE_DAYS)
    for proj in state.get("projects", {}).values():
        proj["open_sessions"] = {
            sid: info for sid, info in proj.get("open_sessions", {}).items()
            if _parse_iso(info.get("started_at")) >= cutoff
        }
    return state

