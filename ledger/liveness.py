"""Is the harness process that opened a session still running?

An open-session marker with no matching SessionEnd is either an orphan (the
harness was killed) or a session that is simply still open in another window.
Recording the harness's pid + kernel start time at SessionStart lets us tell
them apart. Start time guards against pid reuse. Linux /proc only; anywhere
else every lookup returns None and markers are treated as dead, which is the
pre-liveness behavior.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Process names that own a session. Hooks run as children (often via `sh -c`),
# so we walk up the ancestry until one of these appears.
HARNESS_NAMES = frozenset({"claude"})
_MAX_DEPTH = 8


def _stat_fields(pid: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm (field 2) is parenthesised and may contain spaces; split after it.
    close = raw.rfind(")")
    if close == -1:
        return None
    return [raw[raw.find("(") + 1:close], *raw[close + 2:].split()]


def proc_start_time(pid: int) -> str | None:
    """Kernel start time (clock ticks since boot) for pid, or None."""
    f = _stat_fields(pid)
    # After comm: state is index 1, so starttime (stat field 22) is index 20.
    return f[20] if f and len(f) > 20 else None


def harness_process() -> tuple[int, str] | None:
    """(pid, start_time) of the nearest harness ancestor, or None."""
    pid = os.getppid()
    for _ in range(_MAX_DEPTH):
        f = _stat_fields(pid)
        if not f:
            return None
        if f[0] in HARNESS_NAMES:
            start = proc_start_time(pid)
            return (pid, start) if start else None
        ppid = int(f[2])
        if ppid <= 1:
            return None
        pid = ppid
    return None


def is_alive(marker: dict[str, Any]) -> bool:
    """True only if the marker's recorded process is provably still running."""
    pid, start = marker.get("pid"), marker.get("pid_start")
    if not pid or not start:
        return False
    return proc_start_time(int(pid)) == start
