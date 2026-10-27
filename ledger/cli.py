"""Typer CLI for ledger."""
from __future__ import annotations

import difflib
import json
import os
from datetime import date as _date
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ledger.config import LedgerConfig, default_config_path, load_config
from ledger.discovery import default_projects_root, discover_projects
from ledger.gitwrite import CommitResult
from ledger.markdown import (
    MarkdownStructureError, SubsectionNotFoundError, backlog_counts,
    most_recent_changelog_entry, idea as md_idea, ship as md_ship, grep_file,
)
from ledger.memory import memory_path_for, read_description
from ledger.models import Project

import sys as _sys

app = typer.Typer(no_args_is_help=True, help="Cross-project changelog and backlog tracker.")
err = Console(stderr=True)
out = Console()


@app.callback(invoke_without_command=True)
def main() -> None:
    """Main entry point."""
    pass


hook_app = typer.Typer(
    hidden=True,
    no_args_is_help=True,
    help="Internal Claude Code hook entry points (not for direct use).",
)
app.add_typer(hook_app, name="hook")


@hook_app.command("session-start")
def _hook_session_start() -> None:
    try:
        raw = _sys.stdin.read() or "{}"
        payload = json.loads(raw)
        from ledger import hooks as _hooks
        out = _hooks.session_start(payload)
        if out is not None:
            _sys.stdout.write(json.dumps(out))
    except Exception:
        pass  # bulletproof: ledger errors must NEVER break a Claude session
    raise typer.Exit(code=0)


@hook_app.command("session-end")
def _hook_session_end() -> None:
    try:
        raw = _sys.stdin.read() or "{}"
        payload = json.loads(raw)
        from ledger import hooks as _hooks
        _hooks.session_end(payload)
    except Exception:
        pass
    raise typer.Exit(code=0)


def _projects_root() -> Path:
    return Path(os.environ.get("LEDGER_PROJECTS_ROOT") or default_projects_root())


def _load_projects(cfg: LedgerConfig | None = None) -> list[Project]:
    """Discover projects; pass cfg when the caller also needs it (e.g. memory overrides)."""
    if cfg is None:
        cfg = load_config(default_config_path())
    return discover_projects(projects_root=_projects_root(), config=cfg)


def _claude_memory(project: Project, no_memory: bool, overrides: dict[str, str]) -> str:
    if no_memory:
        return ""
    override = overrides.get(project.slug)
    path = memory_path_for(project.slug, override=override)
    desc = read_description(path)
    return desc or ""


@app.command()
def status(
    memory: bool = typer.Option(False, "--memory", help="Add a column with Claude's note on each project."),
    no_memory: bool = typer.Option(False, "--no-memory", hidden=True, envvar="LEDGER_NO_MEMORY"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
):
    """What each project last finished and what's next."""
    from rich.markup import escape
    from ledger import display
    from ledger.parse import parse_backlog
    cfg = load_config(default_config_path())
    projects = _load_projects(cfg)
    today = _date.today()

    rows: list[dict] = []
    for p in projects:
        entry = most_recent_changelog_entry(p.changelog_path)
        counts = backlog_counts(p.backlog_path)
        next_up = next((i.headline for i in parse_backlog(p.backlog_path)
                        if i.section == "Now" and not i.done), None)
        rows.append({
            "slug": p.slug,
            "path": str(p.path),
            "last_shipped_date": entry[0] if entry else None,
            "last_shipped_title": entry[1] if entry else None,
            "next_up": next_up,
            "backlog": counts,
            # JSON always carries the note; --memory only adds the table column.
            "memory": _claude_memory(p, no_memory or not (memory or json_out), cfg.memory_overrides),
        })

    if json_out:
        print(json.dumps(rows, indent=2))
        return

    # expand=True + ratio on LAST FINISHED/NEXT UP lets those two share
    # whatever width is left over after the fixed columns, instead of the
    # old fixed max_width=52 each starving PROJECT/NOW/LATER down to 0 at
    # narrow terminals (Rich's overflow "last resort" step squeezes ALL
    # columns evenly once the fixed ones alone exceed the terminal width).
    table = Table(show_lines=False, padding=(0, 1), expand=True)
    project_width = max([len(r["slug"]) for r in rows] + [len("PROJECT")])
    table.add_column("PROJECT", style="bold", no_wrap=True, min_width=project_width)
    table.add_column("LAST FINISHED", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("NEXT UP", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("NOW", justify="right", no_wrap=True, min_width=max(len("NOW"), 3))
    table.add_column("LATER", justify="right", no_wrap=True, min_width=max(len("LATER"), 3))
    if memory:
        # ratio=1, not a fixed max_width: a fixed column here counts fully
        # against the terminal width alongside PROJECT/NOW/LATER and can
        # trigger the same last-resort squeeze at narrow terminals; making
        # it flexible like LAST FINISHED/NEXT UP lets all three share space.
        table.add_column("MEMORY", overflow="ellipsis", no_wrap=True, ratio=1)
    for r in rows:
        when = display.relative_date(r["last_shipped_date"], today)
        last = (f"{when} · {display.clamp_chars(display.plain(r['last_shipped_title'] or ''))}"
                if r["last_shipped_date"] else "—")
        # plain() before clamping: a clamp can cut a link in half, and half a
        # link stays raw.
        nxt = display.clamp_words(display.plain(r["next_up"]))[0] if r["next_up"] else "—"
        c = r["backlog"]
        # escape(): headlines contain [tag] brackets Rich would read as markup.
        cells = [r["slug"], escape(last), escape(nxt), str(c["now"]), str(c["soon"] + c["someday"])]
        if memory:
            cells.append(escape(r["memory"] or "—"))
        table.add_row(*cells)
    out.print(table)


def _print_violation(e: "RuleViolation") -> None:
    """Report a rules.RuleViolation the same way for `ship` and `idea`."""
    from rich.markup import escape
    err.print("Ledger didn't save this. Fix these and try again:")
    for p in e.problems:
        err.print(f"  - {escape(p.message)}")
    err.print("Run `ledger rules` to see all the rules.", markup=False)


def _report_skipped_commit(result: CommitResult) -> None:
    """Say so when the file was written but git didn't commit it (detached HEAD, mid-rebase)."""
    if not result.committed and result.skipped_reason and result.skipped_reason != "nothing to commit":
        err.print(f"  (commit skipped: {result.skipped_reason})", markup=False)


def _resolve_project_or_exit(slug: str) -> Project:
    projects = _load_projects()
    by_slug = {p.slug: p for p in projects}
    if slug in by_slug:
        return by_slug[slug]
    suggestions = difflib.get_close_matches(slug, list(by_slug.keys()), n=1, cutoff=0.6)
    if suggestions:
        err.print(f"no project '{slug}'. Did you mean '{suggestions[0]}'?")
    else:
        err.print(f"no project '{slug}'. Known: {', '.join(sorted(by_slug)) or '(none)'}.")
    raise typer.Exit(code=2)


@app.command()
def idea(
    project: str = typer.Argument(..., help="Project slug."),
    text: str = typer.Argument(..., help="Backlog item text."),
    now: bool = typer.Option(False, "--now"),
    someday: bool = typer.Option(False, "--someday"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Tag like 'bug', 'feat'."),
    section: Optional[str] = typer.Option(None, "--section",
        help="H3 sub-section inside the target horizon (case-sensitive verbatim match)."),
    note: Optional[str] = typer.Option(None, "--note",
        help="Working detail for whoever picks this up. Code names are fine here."),
):
    """Append an item to <project>/docs/BACKLOG.md."""
    if now and someday:
        err.print("--now and --someday are mutually exclusive.")
        raise typer.Exit(code=2)
    horizon = "Now" if now else "Someday" if someday else "Soon"
    tag = tag.strip() if tag else tag  # the web form strips; match it
    p = _resolve_project_or_exit(project)
    from ledger import writer
    from ledger.rules import RuleViolation
    try:
        result = writer.add_backlog_item(
            p, text=text, horizon=horizon, tag=tag, sub_section=section, note=note,
        )
    except RuleViolation as e:
        _print_violation(e)
        raise typer.Exit(1)
    except SubsectionNotFoundError as e:
        err.print(f"sub-section '### {e}' not found under '## {horizon}'.")
        raise typer.Exit(code=2)
    except MarkdownStructureError as e:
        err.print(str(e))
        raise typer.Exit(code=2)
    from rich.markup import escape
    tag_str = f", [{tag}]" if tag else ""
    # escape(): Rich would read "[bug]" as markup and drop it.
    out.print(escape(f"✓ added to {p.backlog_path} ({horizon}{tag_str})"))
    _report_skipped_commit(result)


_SHIP_TEMPLATE = """
# Ship an entry to {slug}'s CHANGELOG.
# First non-comment line is the title; anything after it is the Why paragraph.
# Lines starting with '#' are ignored. Leave it empty to abort.
"""


def _ship_entry_from_editor(slug: str) -> tuple[str | None, str | None]:
    """Collect (title, why) from $EDITOR on a scratch file, like `git commit`.

    Editing a scratch file (not CHANGELOG.md directly) means closing the editor
    unchanged leaves the CHANGELOG untouched instead of stranding a placeholder
    entry for the next auto-commit to pick up. Returns (None, None) to abort.
    """
    import shlex
    import subprocess
    import tempfile
    editor = shlex.split(os.environ.get("EDITOR", "nano"))
    fd, tmp = tempfile.mkstemp(prefix="ledger-ship.", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_SHIP_TEMPLATE.format(slug=slug))
        if subprocess.run([*editor, tmp]).returncode != 0:
            return None, None
        text = Path(tmp).read_text(encoding="utf-8")
    finally:
        os.unlink(tmp)
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(lines).strip()
    if not body:
        return None, None
    title, _, rest = body.partition("\n")
    return title.strip(), (rest.strip() or None)


@app.command()
def ship(
    project: str = typer.Argument(..., help="Project slug."),
    title: Optional[str] = typer.Argument(None, help="Entry title (omit to open $EDITOR)."),
    why: Optional[str] = typer.Option(None, "--why", help="Inline Why paragraph."),
):
    """Prepend a CHANGELOG entry under today's date (or append H3 if today exists)."""
    p = _resolve_project_or_exit(project)
    today = _date.today().isoformat()
    if title is None:
        title, why = _ship_entry_from_editor(p.slug)
        if title is None:
            err.print("aborted: empty entry, nothing shipped")
            raise typer.Exit(1)
    from ledger import writer
    from ledger.rules import RuleViolation
    try:
        result = writer.add_changelog_entry(p, title=title, why=why)
    except RuleViolation as e:
        _print_violation(e)
        raise typer.Exit(1)
    out.print(f"✓ added to {p.changelog_path} ({today})")
    _report_skipped_commit(result)


@app.command()
def edit(
    project: str = typer.Argument(..., help="Project slug."),
    log: bool = typer.Option(False, "--log", help="Edit CHANGELOG.md instead of BACKLOG.md."),
    memory: bool = typer.Option(False, "--memory", help="Edit the project's auto-memory file."),
):
    """Open BACKLOG.md (or CHANGELOG.md, or memory file) in $EDITOR."""
    if log and memory:
        err.print("--log and --memory are mutually exclusive.")
        raise typer.Exit(code=2)
    p = _resolve_project_or_exit(project)
    if memory:
        cfg = load_config(default_config_path())
        override = cfg.memory_overrides.get(p.slug)
        target = memory_path_for(p.slug, override=override)
    elif log:
        target = p.changelog_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
    else:
        target = p.backlog_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
    editor = os.environ.get("EDITOR", "nano")
    os.execvp(editor, [editor, str(target)])


@app.command()
def init(
    project: str = typer.Argument(..., help="Project slug to scaffold."),
):
    """Scaffold docs/BACKLOG.md and docs/CHANGELOG.md if missing.

    Idempotent: existing files are left untouched.
    """
    from ledger.markdown import (
        BACKLOG_TEMPLATE, CHANGELOG_TEMPLATE, _atomic_write,
    )
    p = _resolve_project_or_exit(project)
    p.docs_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for path, template in [
        (p.backlog_path, BACKLOG_TEMPLATE),
        (p.changelog_path, CHANGELOG_TEMPLATE),
    ]:
        if not path.exists():
            _atomic_write(path, template.format(name=p.slug))
            created.append(path.name)
    if created:
        out.print(f"✓ created: {', '.join(created)}")
    else:
        out.print(f"already initialized: {p.docs_dir}")


@app.command()
def done(
    project: str = typer.Argument(..., help="Project slug."),
    text: str = typer.Argument(..., help="Words from the finished item's headline."),
):
    """Move a finished backlog item to the Done list."""
    from rich.markup import escape
    from ledger import archive, writer
    from ledger.display import clamp_words
    p = _resolve_project_or_exit(project)
    if not text.strip():
        err.print("Give some words from the finished item's headline.", markup=False)
        raise typer.Exit(2)
    try:
        item, result = writer.mark_done(p, text)
    except archive.NoMatch:
        err.print(f"No open item in {p.slug} matches “{escape(text)}”.")
        # markup=False already prints the text as-is; escape() would add a backslash.
        err.print(f'Try: ledger search "{text}" --project {p.slug} --bag', markup=False)
        raise typer.Exit(1)
    except archive.BacklogChanged as e:
        err.print(str(e), markup=False)
        raise typer.Exit(1)
    except archive.AmbiguousMatch as e:
        err.print(f"{len(e.items)} open items match “{escape(text)}”. Use more words from the one you mean:")
        for i in e.items[:10]:
            err.print(f"  - {escape(clamp_words(i.headline, 15)[0])}")
        raise typer.Exit(1)
    out.print(f"✓ moved to the Done list: {escape(item.headline)}")
    _report_skipped_commit(result)


@app.command()
def tidy(
    projects: Optional[list[str]] = typer.Argument(None, help="Project slugs."),
    all_: bool = typer.Option(False, "--all", help="Every project."),
    skip: list[str] = typer.Option([], "--skip", help="Project to leave out. Repeatable."),
):
    """Move finished items out of each backlog into its Done list."""
    from rich.markup import escape
    from ledger import archive, writer
    from ledger.display import clamp_words
    if all_ == bool(projects):
        err.print("Name one or more projects, or use --all.", markup=False)
        raise typer.Exit(2)
    targets = _load_projects() if all_ else [_resolve_project_or_exit(s) for s in projects]
    failed = False
    for p in targets:
        if p.slug in skip or not p.backlog_path.exists():
            continue
        try:
            moved, review, result = writer.tidy(p)
        except archive.BacklogChanged as e:
            err.print(f"{p.slug}: {e}", markup=False)
            failed = True
            continue
        out.print(f"{p.slug}: moved {len(moved)} finished item{'s' if len(moved) != 1 else ''}")
        if result is not None:
            _report_skipped_commit(result)
        if review:
            out.print("  Still open but they mention DONE, FIXED or SHIPPED. Check by hand:")
            for i in review:
                out.print(f"    - {escape(clamp_words(i.headline, 15)[0])}")
    if failed:
        raise typer.Exit(1)


@app.command()
def search(
    term: str = typer.Argument(..., help="Substring to search for."),
    project: Optional[str] = typer.Option(None, "--project", help="Scope to one project."),
    log: bool = typer.Option(False, "--log", help="Scope to CHANGELOG only."),
    bag: bool = typer.Option(False, "--bag", help="Scope to BACKLOG only."),
):
    """Substring grep across all projects' CHANGELOG + BACKLOG."""
    if not term:
        err.print("search term must not be empty.")
        raise typer.Exit(code=2)
    case_sensitive = term.startswith('"') and term.endswith('"') and len(term) >= 2
    needle = term[1:-1] if case_sensitive else term

    projects = _load_projects()
    if project:
        projects = [p for p in projects if p.slug == project]
        if not projects:
            err.print(f"no project '{project}'.")
            raise typer.Exit(code=2)

    any_hit = False
    for p in projects:
        for label, path in [("CHANGELOG.md", p.changelog_path),
                            ("BACKLOG.md", p.backlog_path),
                            ("BACKLOG-DONE.md", p.done_path)]:
            if log and label != "CHANGELOG.md":
                continue
            if bag and label not in ("BACKLOG.md", "BACKLOG-DONE.md"):
                continue
            for line_no, line in grep_file(path, needle, case_sensitive=case_sensitive):
                any_hit = True
                # markup=False: file lines hold [tag] brackets Rich would eat.
                out.print(f"{p.slug:25} {label}:{line_no:<5} {line.strip()}", markup=False)
    if not any_hit:
        out.print(f"(no matches for {term!r})", markup=False)


@app.command()
def rules():
    """Print the writing rules. AI tools: read these before writing to ledger."""
    from ledger.rules import RULES_TEXT
    typer.echo(RULES_TEXT, nl=False)


@app.command()
def check(
    project: Optional[str] = typer.Argument(None, help="One project, or leave out for all."),
    since: str = typer.Option("30d", "--since", help="How far back to check changelog entries, like 30d."),
    skip: list[str] = typer.Option([], "--skip", help="Project to leave out. Repeatable."),
):
    """List recent changelog entries and open Now items that break the rules."""
    import re as _re
    from datetime import timedelta
    from rich.markup import escape
    from ledger import rules as _rules
    from ledger.display import clamp_chars
    from ledger.parse import parse_backlog, parse_changelog
    m = _re.fullmatch(r"(\d+)d", since)
    if not m:
        err.print("--since takes a number of days, like 30d.", markup=False)
        raise typer.Exit(2)
    cutoff = (_date.today() - timedelta(days=int(m.group(1)))).isoformat()
    projects = [_resolve_project_or_exit(project)] if project else _load_projects()
    failures = 0
    for p in projects:
        if p.slug in skip:
            continue
        for e in parse_changelog(p.changelog_path):
            if e.date < cutoff:
                continue
            probs = _rules.check_entry(e.title, e.why)
            if probs:
                failures += 1
                out.print(f"{p.slug} · changelog {e.date} · “{escape(clamp_chars(e.title, 50))}”")
                for pr in probs:
                    out.print(f"    - {escape(pr.message)}")
        for it in parse_backlog(p.backlog_path):
            if it.section != "Now" or it.done:
                continue
            # Headline only: the rewrite moves old wording into the note so no
            # working detail is lost, so existing notes may exceed the limit.
            probs = _rules.check_item(it.headline)
            if probs:
                failures += 1
                out.print(f"{p.slug} · Now · “{escape(clamp_chars(it.headline, 50))}”")
                for pr in probs:
                    out.print(f"    - {escape(pr.message)}")
    if failures:
        out.print(f"{failures} need rewriting.")
        raise typer.Exit(1)
    out.print("Everything checked follows the rules.")


@app.command()
def serve(
    port: int = typer.Option(7777, "--port"),
    bind: str = typer.Option("127.0.0.1", "--bind"),
):
    """Start the ledger web dashboard (foreground)."""
    if bind == "0.0.0.0":
        out.print(
            f"[yellow]bound to 0.0.0.0:{port} — accessible on LAN. "
            f"No auth; home-LAN trust model only.[/yellow]"
        )
    LOOPBACK = {"127.0.0.1", "localhost", "::1"}
    os.environ["LEDGER_ALLOW_WRITES"] = "1" if bind in LOOPBACK else "0"
    import uvicorn
    from ledger.web import app as web_app
    uvicorn.run(web_app, host=bind, port=port, log_level="info")
