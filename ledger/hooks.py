"""Hook brains: pure functions invoked by `ledger hook ...` CLI subcommands.

CONTRACT: these functions MUST never raise. Any unexpected error → return
`None` (or no-op). The CLI wrapper additionally catches and exits 0 — two
layers of bulletproofing so a broken ledger can never break a Claude session.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Any

from ledger.config import default_config_path, load_config
from ledger.discovery import default_projects_root, discover_projects
from ledger.models import Project
from ledger import markdown, state as state_mod

MAX_CTX_BYTES = 9500  # under the 10k additionalContext cap, with headroom


def _projects_root() -> Path:
    return Path(os.environ.get("LEDGER_PROJECTS_ROOT") or default_projects_root())


def _resolve_project_for_cwd(cwd: Path) -> Project | None:
    try:
        cfg = load_config(default_config_path())
        projects = discover_projects(projects_root=_projects_root(), config=cfg)
    except Exception:
        return None
    cwd = cwd.resolve()
    for p in projects:
        try:
            cwd.relative_to(p.path)
            return p
        except ValueError:
            continue
    return None


ADDED_RE = re.compile(r"<!--\s*added\s+(\d{4}-\d{2}-\d{2})\s*-->")


def _git(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(["git"] + args, cwd=cwd,
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _rev_parse_head(repo: Path) -> str | None:
    return _git(["rev-parse", "HEAD"], repo) or None


def _count_added_since(backlog_path: Path, since_iso: str | None) -> int:
    if not backlog_path.exists() or not since_iso:
        return 0
    try:
        cutoff = _date.fromisoformat(since_iso[:10])
    except ValueError:
        return 0
    n = 0
    for m in ADDED_RE.finditer(backlog_path.read_text(encoding="utf-8")):
        try:
            if _date.fromisoformat(m.group(1)) > cutoff:
                n += 1
        except ValueError:
            pass
    return n


def _build_summary(project: Project, added_since: int,
                   pending_stub: bool, orphan_note: str | None) -> str:
    from ledger import display
    counts = markdown.backlog_counts(project.backlog_path)
    later = counts["soon"] + counts["someday"]
    recent = markdown.most_recent_changelog_entry(project.changelog_path)
    today = _date.today()
    line = f"📋 Ledger · {project.slug}: {counts['now']} to do now, {later} later"
    if recent:
        title = display.plain(display.clamp_chars(recent[1]))
        line += f" · last finished {display.relative_date(recent[0], today)}: “{title}”"
    if added_since:
        line += f" · {added_since} added since your last visit"
    if pending_stub:
        line += " · 1 session still needs a changelog entry"
    line += "."
    return f"{line}\n{orphan_note}" if orphan_note else line


def _instruction(source: str, summary: str) -> str:
    greet = source in ("startup", "clear")
    intro = (
        "Open this reply with the one-line summary below verbatim, then proceed with the user's first message. Expand on request."
        if greet else
        "Background context — do not announce; reference only when relevant."
    )
    return (
        f"<ledger>\n{intro}\n\nSUMMARY:\n{summary}\n\n"
        "Before writing to ledger this session, run `ledger rules` and follow them. "
        "Record finished work with `ledger ship` (do it without asking), new backlog "
        "items with `ledger idea`, and finished items with `ledger done`. Never edit "
        "CHANGELOG.md or BACKLOG.md directly. Ledger refuses text that breaks the "
        "rules; fix the text and run the command again.\n</ledger>"
    )


def _emit(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_CTX_BYTES:
        text = text.encode("utf-8")[:MAX_CTX_BYTES].decode("utf-8", errors="ignore")
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": text,
        }
    }


def _orphan_note(state: dict[str, Any], slug: str, current_head: str | None,
                 current_sid: str, repo: Path) -> str | None:
    """Summarise every dead session that left commits uncaptured.

    Commits are unioned across sessions, so overlapping ranges count once.
    Dead markers that did no work are dropped here: there is nothing to
    capture, and they would otherwise linger until the 30-day GC. Markers
    with commits stay until a `ledger ship` records the work.
    """
    from ledger import liveness
    proj = state_mod.get_project(state, slug)
    shas: set[str] = set()
    orphans = 0
    idle: list[str] = []
    for sid, info in proj["open_sessions"].items():
        if sid == current_sid or liveness.is_alive(info):
            continue
        start = info.get("start_head")
        if not start or not current_head:
            continue
        new = set(_git(["rev-list", f"{start}..{current_head}"], repo).split())
        if new:
            orphans += 1
            shas |= new
        else:
            idle.append(sid)
    for sid in idle:
        proj["open_sessions"].pop(sid, None)
    if not orphans:
        return None
    n = len(shas)
    sess = "session" if orphans == 1 else "sessions"
    commits = "commit" if n == 1 else "commits"
    return (f"⚠️ {orphans} earlier {sess} ended without a changelog entry "
            f"({n} {commits} since). Say \"capture the missed sessions\".")


def session_start(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return a hookSpecificOutput dict for the harness, or None for no-op."""
    try:
        cwd = Path(payload.get("cwd", ".")).resolve()
        source = payload.get("source", "startup")
        sid = payload.get("session_id", "")
        project = _resolve_project_for_cwd(cwd)
        if project is None:
            return None
        if not project.backlog_path.exists() and not project.changelog_path.exists():
            if source in ("startup", "clear"):
                return _emit(
                    f"📋 ledger · {project.slug} — not tracked yet. "
                    f"Run `ledger init {project.slug}` to start."
                )
            return None
        head = _rev_parse_head(project.path)
        # Whole read-modify-write under the lock, so a concurrent hook can't
        # drop this marker or re-commit a stub we've already cleared.
        with state_mod.locked_state() as state:
            proj_state = state_mod.get_project(state, project.slug)
            # If a SessionEnd left SESSIONS.md uncommitted, commit it now.
            if proj_state.get("stub_pending"):
                from ledger import gitwrite
                gitwrite.commit_file(
                    project.path, "docs/SESSIONS.md",
                    "docs(sessions): record stub from prior session",
                )
                proj_state["stub_pending"] = False
            orphan = _orphan_note(state, project.slug, head, sid, project.path)
            added_since = _count_added_since(project.backlog_path,
                                             proj_state.get("last_seen_at"))
            summary = _build_summary(project, added_since,
                                     pending_stub=False, orphan_note=orphan)
            # Record this session's marker
            from ledger import liveness
            harness = liveness.harness_process()
            state_mod.add_open_session(
                state, project.slug, sid,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                head,
                pid=harness[0] if harness else None,
                pid_start=harness[1] if harness else None,
            )
            proj_state["last_seen_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            proj_state["last_seen_head"] = head
        return _emit(_instruction(source, summary))
    except Exception:
        return None


def session_end(payload: dict[str, Any]) -> None:
    """Append a stub to docs/SESSIONS.md and clear the open marker.

    Deliberately minimal: NO git commit here (see spec §5 — the kill-before-
    finish bug). The atomic file append happens first; the commit happens on
    the next SessionStart's reconciliation step.
    """
    try:
        cwd = Path(payload.get("cwd", ".")).resolve()
        sid = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path") or None
        project = _resolve_project_for_cwd(cwd)
        if project is None:
            return None
        head = _rev_parse_head(project.path)
        branch = _git(["symbolic-ref", "--short", "-q", "HEAD"], project.path) or None
        last_user = _last_user_message(transcript_path) if transcript_path else None
        with state_mod.locked_state() as state:
            proj_state = state_mod.get_project(state, project.slug)
            start_head = proj_state["open_sessions"].get(sid, {}).get("start_head")
            diff_stat = ""
            subjects: list[str] = []
            if start_head and head and start_head != head:
                diff_stat = _git(["diff", "--stat", f"{start_head}..{head}"], project.path)
                log = _git(["log", "--oneline", f"{start_head}..{head}"], project.path)
                subjects = [ln for ln in log.splitlines() if ln.strip()]
            if diff_stat or subjects:
                from ledger import writer
                writer.append_session_stub(
                    project, session_id=sid, branch=branch,
                    diff_stat=diff_stat, commit_subjects=subjects,
                    last_user_msg=last_user,
                )
                proj_state["stub_pending"] = True
            state_mod.clear_open_session(state, project.slug, sid)
        return None
    except Exception:
        return None


def _last_user_message(transcript_path: str) -> str | None:
    """Best-effort: read the last human user message from a JSONL transcript.

    Claude Code transcript records look like:
        {"type": "user", "userType": "external",
         "message": {"role": "user", "content": "the prompt"}}
    where `content` can also be a list of mixed text + tool_result blocks:
        {"message": {"content": [{"type": "text", "text": "…"},
                                  {"type": "tool_result", …}]}}
    Tool-result-only continuation records carry `userType: "internal"`; skip
    those so we return what the *human* last typed.
    """
    try:
        last: str | None = None
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "user":
                    continue
                if rec.get("userType") not in (None, "external"):
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict):
                    # Tolerate flatter older shapes (rare): {"type":"user","content":"…"}
                    msg = rec
                content = msg.get("content")
                if isinstance(content, str):
                    stripped = content.strip()
                    # Skip Claude Code's synthetic slash-command echo records
                    # (<local-command-stdout>…, <command-name>…, <local-command-caveat>…).
                    if stripped and not stripped.startswith(("<local-command-", "<command-")):
                        last = content
                elif isinstance(content, list):
                    texts = [
                        block.get("text") for block in content
                        if isinstance(block, dict)
                        and block.get("type") == "text"
                        and isinstance(block.get("text"), str)
                        and block.get("text").strip()
                    ]
                    if texts:
                        last = "\n".join(texts)
        return last
    except OSError:
        return None
