"""What each web page shows, as plain dicts. Templates only lay these out.

Keeping the decisions here (what counts as next, how long text is clamped,
which items are done) makes them testable without rendering HTML.
"""
from __future__ import annotations

import re
from datetime import date

from markupsafe import Markup

from ledger import display
from ledger.rules import HEADLINE_MAX_WORDS
from ledger.markdown import render_text
from ledger.models import Project
from ledger.parse import Entry, Item, parse_backlog, parse_changelog, parse_done

RECENT_SHOWN = 10
_EMPH_RE = re.compile(r"\*\*|~~|__")


def _clean(text: str) -> str:
    """One line without emphasis or link markup; `code` stays for inline_html."""
    return " ".join(_EMPH_RE.sub("", display.strip_links(text)).split())


def item_view(it: Item, today: date) -> dict:
    short, overflow = display.clamp_words(_clean(it.headline))
    note_md = "\n\n".join(x for x in (overflow, it.note) if x)
    return {
        "headline": display.inline_html(short),
        "note_html": render_text(note_md),
        "tags": [display.tag_label(t) for t in it.tags],
        "added": display.relative_date(it.added, today) if it.added else "",
        "added_iso": it.added or "",
    }


def entry_view(e: Entry, today: date) -> dict:
    full = _clean(e.title)
    title = display.clamp_chars(full)
    more = e.more
    if title != full:
        # The display title is shortened; keep the whole original in the fold.
        more = full + ("\n\n" + more if more else "")
    return {
        "date": e.date,
        "when": display.relative_date(e.date, today),
        "title": display.inline_html(title),
        "why": display.inline_html(_clean(e.why)),
        "more_html": render_text(more),
    }


def _status(entries: list[Entry], today: date) -> tuple[int | None, str, str]:
    age = display.age_days(entries[0].date, today) if entries else None
    key, label = display.status(age)
    return age, key, label


def dashboard(projects: list[Project], today: date) -> dict:
    rows = []
    for p in projects:
        entries = parse_changelog(p.changelog_path)
        items = parse_backlog(p.backlog_path)
        age, key, label = _status(entries, today)
        now = [i for i in items if i.section == "Now" and not i.done]
        later = [i for i in items if i.section != "Now" and not i.done]
        last = entries[0] if entries else None
        name = display.display_name(p)
        next_text = display.clamp_words(_clean(now[0].headline))[0] if now else None
        rows.append({
            "slug": p.slug, "name": name,
            "status_key": key, "status_label": label, "age": age,
            "last_date": last.date if last else None,
            "last_when": display.relative_date(last.date, today) if last else "",
            "last_title": display.inline_html(display.clamp_chars(_clean(last.title))) if last else None,
            "next_up": display.inline_html(next_text) if next_text else None,
            "now": len(now), "later": len(later),
            "search_text": " ".join([name, display.plain(last.title) if last else "",
                                     display.plain(next_text or "")]).lower(),
        })
    # Recency first; never-shipped last; name breaks ties. Matches the
    # "Recently active" sort so the page doesn't reorder when JS loads.
    rows.sort(key=lambda r: (r["age"] is None, r["age"] or 0, r["name"].lower()))
    summary = {
        "projects": len(rows),
        "shipped_week": sum(1 for r in rows if r["age"] is not None and r["age"] <= 7),
        "now_total": sum(r["now"] for r in rows),
        "quiet": sum(1 for r in rows if r["age"] is not None and r["age"] > 30),
    }
    return {"rows": rows, "summary": summary}


def project(p: Project, today: date) -> dict:
    entries = parse_changelog(p.changelog_path)
    items = parse_backlog(p.backlog_path)
    _, key, label = _status(entries, today)
    now = [i for i in items if i.section == "Now" and not i.done]
    groups: list[dict] = []
    for it in now:
        if not groups or groups[-1]["subsection"] != it.subsection:
            groups.append({"subsection": it.subsection, "items": []})
        groups[-1]["items"].append(item_view(it, today))
    later = {h: [item_view(i, today) for i in items if i.section == h and not i.done]
             for h in ("Soon", "Someday")}
    # Items still marked done inside BACKLOG.md (not yet tidied) show as done too.
    done = ([item_view(i, today) for i in items if i.done]
            + [item_view(i, today) for i in parse_done(p.done_path)])
    return {
        "slug": p.slug, "name": display.display_name(p),
        "status_key": key, "status_label": label, "path": str(p.path),
        "now_count": len(now), "later_count": sum(len(v) for v in later.values()),
        "up_next": groups, "later": later,
        "finished": [entry_view(e, today) for e in entries],
        "recent_shown": RECENT_SHOWN, "done": done,
        "has_changelog": p.changelog_path.exists(), "has_backlog": p.backlog_path.exists(),
    }


def _snippet(text: str, needle: str, case_sensitive: bool) -> Markup | str:
    plain = display.plain(text)
    hay, ndl = (plain, needle) if case_sensitive else (plain.lower(), needle.lower())
    k = hay.find(ndl)
    if k == -1:
        return ""
    start, end = max(0, k - 80), min(len(plain), k + len(needle) + 80)
    piece = ("…" if start else "") + plain[start:end] + ("…" if end < len(plain) else "")
    return display.highlight(piece, needle, case_sensitive)


def search(projects: list[Project], needle: str, case_sensitive: bool, today: date) -> list[dict]:
    def has(text: str) -> bool:
        return (needle in text) if case_sensitive else (needle.lower() in text.lower())

    groups = []
    for p in projects:
        hits = []
        for e in parse_changelog(p.changelog_path):
            if has(e.title) or has(e.why) or has(e.more):
                # plain(), not _clean(): a hit is highlighted plain text, so
                # `code` backticks would show as-is.
                title = display.clamp_chars(display.plain(e.title))
                hits.append({
                    "kind": "Finished", "when": display.relative_date(e.date, today),
                    "text": display.highlight(title, needle, case_sensitive),
                    "snippet": "" if has(title) else _snippet(e.why + " " + e.more, needle, case_sensitive),
                })
        backlog = parse_backlog(p.backlog_path)
        for kind, pool in (("To do", [i for i in backlog if not i.done]),
                           ("Done", [i for i in backlog if i.done] + parse_done(p.done_path))):
            for it in pool:
                if has(it.headline) or has(it.note):
                    # plain() before clamping, like the changelog hits: a
                    # clamp can cut a link in half, and half a link stays raw.
                    head = display.clamp_words(display.plain(it.headline), HEADLINE_MAX_WORDS)[0]
                    hits.append({
                        "kind": kind, "when": display.relative_date(it.added, today) if it.added else "",
                        "text": display.highlight(head, needle, case_sensitive),
                        "snippet": "" if has(head) else _snippet(it.note, needle, case_sensitive),
                    })
        if hits:
            groups.append({"slug": p.slug, "name": display.display_name(p), "hits": hits})
    return groups
