"""Move finished backlog items to docs/BACKLOG-DONE.md.

`ledger done` moves one item as it is finished; `ledger tidy` sweeps a
backlog once for items already marked done. Moving (not deleting) keeps the
history searchable while BACKLOG.md shows only open work.
"""
from __future__ import annotations

import re

from ledger.display import display_name
from ledger.markdown import _atomic_write
from ledger.models import Project
from ledger.parse import Item

DONE_INTRO = "Finished backlog items, moved here by `ledger done` and `ledger tidy`. Newest first."
# Open items whose text claims they're finished. Listed for a person to
# decide; never moved automatically, because the word is often about a part.
_REVIEW_RE = re.compile(r"\b(?:DONE|FIXED|SHIPPED)\b")


class NoMatch(Exception):
    pass


class BacklogChanged(Exception):
    """BACKLOG.md no longer matches what was read, so a cut could hit the wrong lines."""

    def __init__(self) -> None:
        super().__init__("The backlog changed while ledger was working. Run the command again.")


class AmbiguousMatch(Exception):
    def __init__(self, items: list[Item]):
        self.items = items
        super().__init__(f"{len(items)} items match")


def find_open_item(items: list[Item], text: str) -> Item:
    needle = text.strip().lower()
    if not needle:
        raise NoMatch(text)  # "" is in every headline; never match them all
    matches = [i for i in items if not i.done and needle in i.headline.lower()]
    if not matches:
        raise NoMatch(text)
    if len(matches) > 1:
        exact = [i for i in matches if i.headline.lower() == needle]
        if len(exact) == 1:
            return exact[0]
        raise AmbiguousMatch(matches)
    return matches[0]


def tidy_plan(items: list[Item]) -> tuple[list[Item], list[Item]]:
    to_move = [i for i in items if i.done]
    to_review = [i for i in items if not i.done and _REVIEW_RE.search(i.raw)]
    return to_move, to_review


def move_items(project: Project, items: list[Item], today: str, mark_done: bool) -> None:
    """Cut `items` out of BACKLOG.md and add them to today's group in BACKLOG-DONE.md.

    Raises BacklogChanged, before writing anything, if the file no longer
    holds each item at the lines it was parsed from.
    """
    lines = project.backlog_path.read_text(encoding="utf-8").splitlines()
    if any("\n".join(lines[it.start:it.end]) != it.raw for it in items):
        raise BacklogChanged()
    for it in sorted(items, key=lambda i: i.start, reverse=True):
        del lines[it.start:it.end]
        # Don't leave a double blank line where the item was.
        if 0 < it.start < len(lines) and not lines[it.start].strip() and not lines[it.start - 1].strip():
            del lines[it.start]

    block: list[str] = []
    for it in sorted(items, key=lambda i: i.start):
        raw = it.raw.split("\n")
        first = re.sub(r"^- \[[ ~]\]", "- [x]", raw[0]) if mark_done else raw[0]
        origin = it.section + (f" › {it.subsection}" if it.subsection else "")
        raw[0] = f"{first} <!-- from {origin} -->"
        block.extend(raw)
    # Done list first: if the second write fails, the items are in both
    # files (easy to tidy) rather than in neither.
    _add_to_done(project, today, block)
    _atomic_write(project.backlog_path, "\n".join(lines).rstrip("\n") + "\n")


def _add_to_done(project: Project, today: str, block: list[str]) -> None:
    path = project.done_path
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    else:
        lines = [f"# {display_name(project)} — Done", "", DONE_INTRO, ""]
    header = f"## {today}"
    if header in lines:
        k = lines.index(header) + 1
        if k < len(lines) and not lines[k].strip():
            k += 1
        lines[k:k] = block
    else:
        # Newest group first: before the first existing date group.
        k = next((n for n, l in enumerate(lines) if l.startswith("## ")), len(lines))
        new = [header, ""] + block + [""]
        if k > 0 and lines[k - 1].strip():
            new = [""] + new
        lines[k:k] = new
    _atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
