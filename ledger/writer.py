"""Single write path for ledger mutations. CLI/web/hooks all route through here.

Each write: atomic file mutation (via markdown.py) then best-effort
`gitwrite.commit_file()`. A failed commit NEVER discards the file write.
"""
from __future__ import annotations

from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from ledger import gitwrite, markdown, rules
from ledger.models import Project

if TYPE_CHECKING:
    from ledger.parse import Item


def add_backlog_item(project: Project, text: str, horizon: str = "Soon",
                     tag: str | None = None,
                     sub_section: str | None = None,
                     note: str | None = None) -> gitwrite.CommitResult:
    problems = rules.check_item(text, note, tag)
    if problems:
        raise rules.RuleViolation(problems)
    today = _date.today().isoformat()
    markdown.idea(project.backlog_path, text=text, today=today,
                  section=horizon, tag=tag, sub_section=sub_section,
                  project_name=project.slug, note=note)
    return gitwrite.commit_file(
        project.path, "docs/BACKLOG.md",
        f"docs(backlog): add item via ledger ({horizon})",
    )


def add_changelog_entry(project: Project, title: str,
                        why: str | None = None) -> gitwrite.CommitResult:
    # The Why is written as one paragraph after `**Why:**`. A line break in
    # it could start a new `## date` header in the file (re-dating every entry
    # below) or split it so only the first part reads as the Why, and a web
    # form sends \r\n. Collapse it before the check so the check sees what
    # gets written.
    why = " ".join(why.split()) if why else why
    # Checked here, the one funnel every writer uses (CLI, web, promote_stub),
    # so no path can skip the rules.
    problems = rules.check_entry(title, why)
    if problems:
        raise rules.RuleViolation(problems)
    today = _date.today().isoformat()
    markdown.ship(project.changelog_path, today=today, title=title, why=why,
                  project_name=project.slug)
    result = gitwrite.commit_file(
        project.path, "docs/CHANGELOG.md",
        f"docs(changelog): ship via ledger — {title[:60]}",
    )
    _clear_captured_orphans(project.slug)
    return result


def _clear_captured_orphans(slug: str) -> None:
    """A ship records the work, so dead sessions' orphan warnings are done.

    Live sessions (another window still open) keep their markers so their
    own SessionEnd can still write a stub. Best-effort: state trouble must
    never fail a ship whose CHANGELOG write already landed.
    """
    from ledger import state as state_mod
    try:
        if not state_mod.load_state().get("projects", {}).get(slug):
            return  # nothing tracked; don't create or rewrite state.json
        with state_mod.locked_state() as st:
            state_mod.prune_dead_sessions(st, slug)
    except Exception:
        pass


def append_session_stub(project: Project, *, session_id: str,
                        branch: str | None, diff_stat: str,
                        commit_subjects: list[str],
                        last_user_msg: str | None) -> None:
    """Append a raw session stub to docs/SESSIONS.md.

    DOES NOT commit — the commit is deferred to the next SessionStart's
    reconciliation step. This is intentional (spec §5): the atomic file
    append must survive a mid-run kill of the SessionEnd hook.
    """
    project.docs_dir.mkdir(parents=True, exist_ok=True)
    path = project.docs_dir / "SESSIONS.md"
    today = _date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    chunks: list[str] = []
    if not path.exists():
        chunks.append(f"# {project.slug} — Sessions\n\n")
        chunks.append(
            "Raw session stubs (auto-captured). Promote meaningful work to "
            "CHANGELOG.md via `ledger ship`; stubs remain as audit trail.\n\n"
        )
    chunks.append(f"## {today}\n\n")
    branch_suffix = f" on `{branch}`" if branch else ""
    chunks.append(f"### {now} — session `{session_id[:8]}`{branch_suffix}\n\n")
    if diff_stat.strip():
        chunks.append("```\n" + diff_stat.strip() + "\n```\n\n")
    if commit_subjects:
        chunks.append("**Commits:**\n")
        for s in commit_subjects:
            chunks.append(f"- {s}\n")
        chunks.append("\n")
    if last_user_msg:
        msg = last_user_msg.strip().replace("\n", " ")
        if len(msg) > 300:
            msg = msg[:300] + "…"
        chunks.append(f"**Last prompt:** {msg}\n\n")
    # Truly atomic: read existing, concatenate, write tmp + rename.
    # Multi-write append via open("a") is NOT atomic and can be torn by SIGKILL,
    # which would defeat the deferred-commit safety pattern.
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    markdown._atomic_write(path, existing + "".join(chunks))


def mark_done(project: Project, text: str) -> tuple["Item", gitwrite.CommitResult]:
    """Move the one open item whose headline contains `text` to the Done list."""
    from ledger import archive
    from ledger.parse import parse_backlog
    item = archive.find_open_item(parse_backlog(project.backlog_path), text)
    archive.move_items(project, [item], _date.today().isoformat(), mark_done=True)
    result = gitwrite.commit_file(
        project.path, ["docs/BACKLOG.md", "docs/BACKLOG-DONE.md"],
        f"docs(backlog): done via ledger — {item.headline[:60]}",
    )
    return item, result


def tidy(project: Project) -> tuple[list["Item"], list["Item"], gitwrite.CommitResult | None]:
    """Move every already-finished item to the Done list. Returns (moved, review, commit)."""
    from ledger import archive
    from ledger.parse import parse_backlog
    move, review = archive.tidy_plan(parse_backlog(project.backlog_path))
    if not move:
        return [], review, None
    archive.move_items(project, move, _date.today().isoformat(), mark_done=False)
    result = gitwrite.commit_file(
        project.path, ["docs/BACKLOG.md", "docs/BACKLOG-DONE.md"],
        f"docs(backlog): move {len(move)} finished items to the Done list via ledger tidy",
    )
    return move, review, result


def promote_stub(project: Project, stub_marker: str, title: str,
                 why: str | None = None) -> gitwrite.CommitResult:
    """Mark a stub as promoted (✓) in SESSIONS.md and add a CHANGELOG entry.

    `stub_marker` is a substring uniquely identifying the stub heading
    (e.g. ``session `sid-dead```). The line containing it gets ' ✓' appended
    if not already present. The CHANGELOG entry is then written + committed
    via `add_changelog_entry()`.
    """
    path = project.docs_dir / "SESSIONS.md"
    if path.exists():
        text = path.read_text(encoding="utf-8")
        new_lines: list[str] = []
        changed = False
        for line in text.splitlines(keepends=True):
            if stub_marker in line and "✓" not in line and not changed:
                stripped = line.rstrip("\n")
                line = stripped + " ✓\n"
                changed = True
            new_lines.append(line)
        if changed:
            markdown._atomic_write(path, "".join(new_lines))
    return add_changelog_entry(project, title, why)
