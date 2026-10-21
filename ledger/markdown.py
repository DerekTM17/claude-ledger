"""Write CHANGELOG.md / BACKLOG.md, plus a few small read helpers.

Reading entries and items lives in parse.py; this module's readers
(`most_recent_changelog_entry`, `backlog_counts`, `grep_file`) build on it or
work line by line. Writes are a line splice plus an atomic temp+rename:
everything outside the insertion stays byte-identical. `render_text` turns a
note or an entry's extra detail into safe HTML for the web pages.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Any `## ` header that starts with a date, including `## 2026-09-10 (later)`:
# parse.parse_changelog treats all of these as date blocks, so ship must too.
DATE_HEADER_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}")
H3_RE = re.compile(r"^### (.+?)\s*$")
H2_RE = re.compile(r"^## (.+?)\s*$")


def most_recent_changelog_entry(path: Path) -> tuple[str, str] | None:
    """Return (date, title) of the newest entry, or None if there are none.

    Built on parse_changelog so `status`, the session greeting and the
    dashboard always agree on what was finished last.
    """
    from ledger.parse import parse_changelog
    entries = parse_changelog(path)
    return (entries[0].date, entries[0].title) if entries else None


def backlog_counts(path: Path) -> dict[str, int]:
    """Open items per horizon. Finished, moved and nested items don't count."""
    from ledger.parse import parse_backlog
    counts = {"now": 0, "soon": 0, "someday": 0}
    for it in parse_backlog(path):
        if not it.done:
            counts[it.section.lower()] += 1
    return counts


CHANGELOG_TEMPLATE = """# {name} — Changelog

Finished work, newest first. Record each piece with `ledger ship`: a short
title and a plain Why. Run `ledger rules` to see the limits.
"""


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp + rename for atomicity. Always LF + trailing newline."""
    if not content.endswith("\n"):
        content += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _read_or_template(path: Path, template: str, name: str) -> str:
    if not path.exists():
        return template.format(name=name)
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("﻿"):
        raw = raw[1:]  # strip BOM
    return raw.replace("\r\n", "\n")


def ship(path: Path, today: str, title: str, why: str | None = None,
         project_name: str | None = None) -> None:
    """Add a CHANGELOG entry under `## <today>`.

    - If `## <today>` header already exists, append a new `### <title>` under it.
    - Otherwise, prepend a new date block before the first existing date block.
    """
    name = project_name or path.parent.parent.name
    content = _read_or_template(path, CHANGELOG_TEMPLATE, name)
    lines = content.splitlines(keepends=True)

    new_h3_block = [f"### {title}\n", "\n"]
    if why:
        new_h3_block += [f"**Why:** {why}\n", "\n"]

    today_header = f"## {today}\n"

    # Case A: today's header already exists — insert ### under it
    for i, line in enumerate(lines):
        if line == today_header:
            insert_at = i + 1
            # Skip blank lines after the H2 to put the H3 right after them
            while insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            for j, new_line in enumerate(new_h3_block):
                lines.insert(insert_at + j, new_line)
            _atomic_write(path, "".join(lines))
            return

    # Case B: no today header — build a new date block and prepend before first existing date
    new_block = [today_header, "\n"] + new_h3_block

    for i, line in enumerate(lines):
        if DATE_HEADER_RE.match(line):
            for j, new_line in enumerate(new_block):
                lines.insert(i + j, new_line)
            _atomic_write(path, "".join(lines))
            return

    # Case C: no existing date blocks — append after intro
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    if lines and lines[-1].strip() != "":
        lines.append("\n")
    lines.extend(new_block)
    _atomic_write(path, "".join(lines))


BACKLOG_TEMPLATE = """# {name} — Backlog

Open work, sorted by when: Now, Soon, Someday. Add items with `ledger idea`
and move finished ones to the Done list with `ledger done`. Run
`ledger rules` to see the limits.

## Now

Work in progress, or next in line.

## Soon

Work to pick up after Now.

## Someday

Ideas to keep for later.

<!-- Suggested tags: bug, feat, perf, tech-debt, docs, ops, security, strategic. Use whatever fits. -->
"""


def _format_item(text: str, today: str, tag: str | None = None,
                 note: str | None = None) -> str:
    prefix = f"**[{tag}]** " if tag else ""
    line = f"- [ ] {prefix}{text} <!-- added {today} -->\n"
    if note and note.strip():
        line += "".join(f"  {l}\n" if l.strip() else "\n"
                        for l in note.strip().splitlines())
    return line


def _find_section_end(lines: list[str], h2_idx: int,
                      sub_h3: str | None = None) -> int:
    """Return the line index where to insert a new item inside a section.

    Insertion point is just before the trailing blank lines that lead to
    the next H2 (or EOF). If sub_h3 is given, narrow to inside that H3.
    """
    n = len(lines)
    # Determine the section's outer end (next H2 or EOF)
    outer_end = n
    for k in range(h2_idx + 1, n):
        if H2_RE.match(lines[k]):
            outer_end = k
            break

    h3_idx = None
    if sub_h3 is None:
        end = outer_end
    else:
        # Find the H3 within [h2_idx+1, outer_end)
        h3_header = f"### {sub_h3}\n"
        for k in range(h2_idx + 1, outer_end):
            if lines[k] == h3_header:
                h3_idx = k
                break
        if h3_idx is None:
            raise SubsectionNotFoundError(sub_h3)
        # H3 ends at the next H3 or the outer_end
        end = outer_end
        for k in range(h3_idx + 1, outer_end):
            if H3_RE.match(lines[k]):
                end = k
                break

    # Insert right after the section's last item, so a trailing comment,
    # rule or footer stays last (spec Appendix A: `idea` used to land after
    # them in Someday).
    from ledger.parse import item_end
    start = h2_idx + 1 if sub_h3 is None else h3_idx + 1
    stripped = [l.rstrip("\n") for l in lines]
    last_end = None
    k = start
    while k < end:
        if re.match(r"^- \[[ xX~→]\]", lines[k].rstrip("\n")):
            last_end = item_end(stripped, k)
            k = last_end
            continue
        k += 1
    if last_end is not None:
        return last_end
    # No items yet: go before trailing blank lines and footer-ish lines
    # (comment-only lines, `---`, italic lines).
    insert_at = end
    footer = re.compile(r"^(?:<!--.*-->|-{3,}|\*[^*].*\*)\s*$")
    while insert_at > start and (lines[insert_at - 1].strip() == ""
                                 or footer.match(lines[insert_at - 1].strip())):
        insert_at -= 1
    return insert_at


class MarkdownStructureError(Exception):
    """Raised when a required header/section is missing."""


class SubsectionNotFoundError(MarkdownStructureError):
    pass


def idea(path: Path, text: str, today: str, section: str = "Soon",
         tag: str | None = None, sub_section: str | None = None,
         project_name: str | None = None, note: str | None = None) -> None:
    """Append an item to BACKLOG under `## <section>` (optionally under `### <sub_section>`)."""
    name = project_name or path.parent.parent.name
    content = _read_or_template(path, BACKLOG_TEMPLATE, name)
    lines = content.splitlines(keepends=True)

    header_line = f"## {section}\n"
    h2_idx = None
    for i, line in enumerate(lines):
        if line == header_line:
            h2_idx = i
            break
    if h2_idx is None:
        raise MarkdownStructureError(
            f"BACKLOG.md doesn't have a `## {section}` header. "
            f"Add it manually or delete the file to lazy-recreate."
        )

    insert_at = _find_section_end(lines, h2_idx, sub_h3=sub_section)
    item = _format_item(text, today, tag, note)
    lines.insert(insert_at, item)
    _atomic_write(path, "".join(lines))


def _md_renderer():
    """Build a markdown-it renderer with GFM checkboxes + anchor IDs."""
    from markdown_it import MarkdownIt
    from mdit_py_plugins.tasklists import tasklists_plugin
    from mdit_py_plugins.anchors import anchors_plugin

    md = MarkdownIt("commonmark", {"html": False, "linkify": True})
    md.enable("table")
    md.enable("strikethrough")
    md.use(tasklists_plugin)
    md.use(anchors_plugin, max_level=3, slug_func=lambda s: s.lower().replace(" ", "-"))
    return md


def render_text(text: str) -> str:
    """Render a markdown fragment (an item note, an entry's extra detail)."""
    return _md_renderer().render(text) if text.strip() else ""


def grep_file(path: Path, term: str, case_sensitive: bool = False) -> list[tuple[int, str]]:
    """Substring grep. Returns list of (line_number_1indexed, line_text)."""
    if not path.exists():
        return []
    needle = term if case_sensitive else term.lower()
    hits = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        hay = line if case_sensitive else line.lower()
        if needle in hay:
            hits.append((i, line))
    return hits
