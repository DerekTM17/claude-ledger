"""Structured reads of BACKLOG.md, BACKLOG-DONE.md and CHANGELOG.md.

The web pages, `ledger check`, `ledger done` and `ledger tidy` read the
files through here instead of rendering them whole, so comments, intro text
and finished items never leak onto the page. Every format variation handled
here is one seen in a real project file.
Pure functions over text; the only I/O is reading the file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HORIZONS = ("Now", "Soon", "Someday")

_ITEM_RE = re.compile(r"^- \[([ xX~→])\]\s?(.*)$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_ADDED_RE = re.compile(r"added\s+(\d{4}-\d{2}-\d{2})")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LEAD_TAG_RE = re.compile(r"[\s*~]*\[([^\]\n]+)\]")
# "**DONE 2026-07-09: [tag] …" / "DONE 2026-07-08 (batch 4b): …" — a status
# prefix written before the tags on some finished items.
_STATUS_PREFIX_RE = re.compile(
    r"^[\s*]*(?:DONE|SHIPPED|CLOSED|FIXED|RESOLVED)\b"
    r"(?:\s+\d{4}-\d{2}-\d{2})?(?:\s*\([^)]*\))?\s*[:—–-]?\s*"
)
# A title wholly struck through, optionally followed by a status word.
_STRUCK_TITLE_RE = re.compile(
    r"\s*~~.+~~\s*(?:(?:DONE|CLOSED|FIXED|SHIPPED|RESOLVED|NOT A BUG)\b.*)?",
    re.S,
)
_LABEL_RE = re.compile(r"^\*\*([^*\n]+?)\*\*:?\s*")
_EMPH_RE = re.compile(r"\*\*|~~|__")
_H1_SUFFIX_RE = re.compile(r"\s+[—–-]\s+(?:Backlog|Changelog|Done)\s*$")
_LIST_OR_TABLE_RE = re.compile(r"^\s*(?:[-*]\s|\d+\.\s|\|)")

DONE_BOXES = frozenset("xX→")


@dataclass
class Item:
    """One backlog item: a top-level `- [ ]` line plus its indented body."""

    headline: str            # first line: tags, comments, bold/strike removed; `code` kept
    note: str                # indented body, dedented, as markdown ("" if none)
    tags: list[str]
    added: str | None        # first "added YYYY-MM-DD" in any of the item's comments
    done: bool
    box: str                 # character inside [ ]: " ", "x", "X", "~" or "→"
    section: str             # "Now"/"Soon"/"Someday", or the date H2 in BACKLOG-DONE.md
    subsection: str | None   # "H3" or "H3 › H4"
    start: int               # 0-based index of the item's first line
    end: int                 # exclusive index after its last line
    raw: str                 # the item's exact source lines joined with "\n"


@dataclass
class Entry:
    """One changelog entry: a `### Title` under a date header."""

    date: str
    title: str
    why: str                 # the Why paragraph, label removed, unwrapped ("" if none)
    more: str                # the rest of the body as markdown ("" if none)
    start: int
    end: int


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    return text.splitlines()


def _comment_open_after(line: str, open_: bool) -> bool:
    """Whether an HTML comment is still open after scanning `line`."""
    pos = 0
    while True:
        token = "-->" if open_ else "<!--"
        k = line.find(token, pos)
        if k == -1:
            return open_
        open_ = not open_
        pos = k + len(token)


def item_end(lines: list[str], i: int) -> int:
    """Exclusive end of the item starting at lines[i].

    The item runs until the next non-blank line at indent 0. A blank line
    belongs to the item only if the next non-blank line is indented. A
    comment left open on one line swallows lines until it closes.
    """
    n = len(lines)
    in_comment = _comment_open_after(lines[i], False)
    j = i + 1
    while j < n:
        line = lines[j]
        if in_comment:
            in_comment = _comment_open_after(line, True)
            j += 1
            continue
        if line.strip() == "":
            k = j
            while k < n and lines[k].strip() == "":
                k += 1
            if k < n and lines[k][:1] == " ":
                j = k
                continue
            break
        if line[:1] != " ":
            break
        in_comment = _comment_open_after(line, False)
        j += 1
    return j


def _dedent(body: str) -> str:
    lines = body.split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    cut = min(indents) if indents else 0
    return "\n".join(l[cut:] for l in lines)


def _split_tags(text: str) -> tuple[list[str], str]:
    s = text
    m = _STATUS_PREFIX_RE.match(s)
    if m:
        s = s[m.end():]
    tags: list[str] = []
    pos = 0
    while (t := _LEAD_TAG_RE.match(s, pos)):
        tags.append(t.group(1).strip())
        pos = t.end()
    return tags, s[pos:]


def _is_struck_title(first_line: str) -> bool:
    title = first_line.split(" — ", 1)[0]
    title = re.sub(r"\[[^\]\n]*\]", "", title).replace("*", "")
    return bool(_STRUCK_TITLE_RE.fullmatch(title))


def _clean_inline(text: str) -> str:
    text = _EMPH_RE.sub("", text)
    text = " ".join(text.split())
    return text.lstrip(" —–:-").strip()


_MARKER_RE = re.compile(r"\*\*|~~")


def _unbalanced(text: str) -> bool:
    return text.count("**") % 2 == 1 or text.count("~~") % 2 == 1


def _carry_open_emphasis(first: str, body: str, reach: int = 3) -> tuple[str, str]:
    """Pull a wrapped headline's tail up from the body when line 1 leaves
    **bold** or ~~strike~~ open.

    Without this, the closing half ("vote event**~~") starts the note and
    shows as raw markup. We cut the body right after the marker that balances
    line 1. If nothing balances within `reach` lines, the split stays as it was.
    """
    if not _unbalanced(first):
        return first, body
    rest = body.split("\n")
    head = first.rstrip()
    for k, line in enumerate(rest[:reach]):
        for m in _MARKER_RE.finditer(line):
            candidate = f"{head} {line[:m.end()].strip()}"
            if not _unbalanced(candidate):
                tail = line[m.end():].strip()
                indent = line[:len(line) - len(line.lstrip(" "))]
                remaining = ([indent + tail] if tail else []) + rest[k + 1:]
                return candidate, "\n".join(remaining)
        head = f"{head} {line.strip()}"
    return first, body


def _make_item(lines: list[str], i: int, j: int, section: str,
               subsection: str | None) -> Item:
    raw_lines = lines[i:j]
    m = _ITEM_RE.match(raw_lines[0])
    box, first = m.group(1), m.group(2)
    joined = "\n".join([first] + raw_lines[1:])
    added = None
    for c in _COMMENT_RE.findall(joined):
        a = _ADDED_RE.search(c)
        if a:
            added = a.group(1)
            break
    clean = _COMMENT_RE.sub("", joined)
    if "<!--" in clean:  # malformed: a comment that never closes
        clean = clean.split("<!--", 1)[0]
    first_clean, _, body = clean.partition("\n")
    first_clean, body = _carry_open_emphasis(first_clean, body)
    tags, rest = _split_tags(first_clean)
    done = box in DONE_BOXES or (box == " " and _is_struck_title(first_clean))
    return Item(
        headline=_clean_inline(rest), note=_dedent(body), tags=tags,
        added=added, done=done, box=box, section=section,
        subsection=subsection, start=i, end=j, raw="\n".join(raw_lines),
    )


def _parse_items(lines: list[str],
                 section_for: Callable[[str], str | None]) -> list[Item]:
    items: list[Item] = []
    section: str | None = None
    h3: str | None = None
    sub: str | None = None
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.startswith("## "):
            section, h3, sub = section_for(line[3:].strip()), None, None
        elif line.startswith("### "):
            h3 = sub = line[4:].strip()
        elif line.startswith("#### "):
            h4 = line[5:].strip()
            sub = f"{h3} › {h4}" if h3 else h4
        elif section and _ITEM_RE.match(line):
            j = item_end(lines, i)
            items.append(_make_item(lines, i, j, section, sub))
            i = j
            continue
        i += 1
    return items


def parse_backlog(path: Path) -> list[Item]:
    """Items under ## Now / Soon / Someday, in file order."""
    def horizon(h2: str) -> str | None:
        return next((h for h in HORIZONS if h.lower() == h2.lower()), None)
    return _parse_items(_read_lines(path), horizon)


def parse_done(path: Path) -> list[Item]:
    """Items in BACKLOG-DONE.md; each item's section is its `## YYYY-MM-DD` group."""
    return _parse_items(_read_lines(path),
                        lambda h2: h2 if _DATE_RE.fullmatch(h2) else None)


def _label(para: list[str]) -> str | None:
    m = _LABEL_RE.match(para[0])
    return m.group(1).strip().rstrip(":").strip().lower() if m else None


def _split_body(body: list[str]) -> tuple[str, str]:
    paras: list[list[str]] = []
    cur: list[str] = []
    for line in body:
        if line.strip() == "---":
            continue
        if line.strip() == "":
            if cur:
                paras.append(cur)
                cur = []
        else:
            cur.append(line)
    if cur:
        paras.append(cur)
    pick = next((k for k, p in enumerate(paras)
                 if (_label(p) or "").startswith("why")), None)
    if pick is None:
        pick = next((k for k, p in enumerate(paras) if _label(p) == "what"), None)
    if pick is None:
        pick = next((k for k, p in enumerate(paras)
                     if not _label(p) and not _LIST_OR_TABLE_RE.match(p[0])), None)
    why = ""
    rest = paras
    if pick is not None:
        p = paras[pick]
        first = _LABEL_RE.sub("", p[0], count=1) if _label(p) else p[0]
        why = " ".join([first.strip()] + [x.strip() for x in p[1:]]).strip()
        rest = paras[:pick] + paras[pick + 1:]
    more = "\n\n".join("\n".join(p) for p in rest)
    return why, more


def parse_changelog(path: Path) -> list[Entry]:
    """Entries in file order (newest first). See Appendix A for date headers."""
    lines = _read_lines(path)
    entries: list[Entry] = []
    date: str | None = None
    cur: tuple[str, str, int] | None = None   # (date, title, start)
    body: list[str] = []

    def close(end: int) -> None:
        if cur is None:
            return
        why, more = _split_body(body)
        e = Entry(date=cur[0], title=cur[1], why=why, more=more,
                  start=cur[2], end=end)
        prev = entries[-1] if entries else None
        # An empty H3 immediately repeated: keep only the copy with the body.
        if (prev and prev.title == e.title and prev.date == e.date
                and not prev.why and not prev.more):
            entries.pop()
        entries.append(e)

    for idx, line in enumerate(lines):
        if line.startswith("## "):
            close(idx)
            cur, body = None, []
            head = line[3:].strip()
            dates = _DATE_RE.findall(head)
            date = max(dates) if dates and _DATE_RE.match(head) else None
        elif line.startswith("### ") and date:
            close(idx)
            cur, body = (date, line[4:].strip(), idx), []
        elif cur is not None:
            body.append(line)
    close(len(lines))
    return entries


def h1_name(path: Path) -> str | None:
    """The file's H1 without the ' — Backlog/Changelog/Done' suffix."""
    for line in _read_lines(path):
        if line.startswith("# "):
            return _H1_SUFFIX_RE.sub("", line[2:].strip()) or None
    return None
