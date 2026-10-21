"""Plain-language display helpers shared by the web pages, CLI and greeting.

Everything a person reads goes through here: dates become "yesterday",
recency becomes "Quiet for 7 weeks", tags become words, and over-long text is
clamped for display (the file itself is never changed).
"""
from __future__ import annotations

import html
import re
from datetime import date

from markupsafe import Markup

from ledger.models import Project
from ledger.parse import h1_name
from ledger.rules import HEADLINE_MAX_WORDS, TITLE_MAX_CHARS

TAG_LABELS = {
    "bug": "Bug", "feat": "Feature", "tech-debt": "Cleanup", "ops": "Operations",
    "docs": "Docs", "perf": "Speed", "security": "Security", "strategic": "Strategy",
}
_EMPH_RE = re.compile(r"\*\*|~~|__|`")
# Block markup that only makes sense in the file: list bullets and checkboxes,
# heading hashes (both at a line start), HTML comments, and link syntax.
_LINE_MARK_RE = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+|(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX~→]\][ \t]+)?)")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\([^)\s]*\)")


def age_days(iso: str | None, today: date) -> int | None:
    if not iso:
        return None
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except ValueError:
        return None


def relative_date(iso: str | None, today: date) -> str:
    if not iso:
        return ""
    n = age_days(iso, today)
    if n is None:
        return iso
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    if n < 14:
        return f"{n} days ago"
    return f"{_weeks_or_months(n)} ago"


def _weeks_or_months(days: int) -> str:
    """'N weeks' while N rounds to under 9 (spec), then 'N months'."""
    weeks = round(days / 7)
    return f"{weeks} weeks" if weeks < 9 else f"{round(days / 30)} months"


def status(age: int | None) -> tuple[str, str]:
    """Recency status as (css key, words). Words always accompany the color."""
    if age is None:
        return "never", "Nothing shipped yet"
    if age <= 0:
        return "today", "Shipped today"
    if age <= 7:
        return "active", "Active this week"
    if age <= 30:
        return "recent", "Active this month"
    return "quiet", f"Quiet for {_weeks_or_months(age)}"


def tag_label(tag: str) -> str:
    t = tag.strip()
    if t.lower() in TAG_LABELS:
        return TAG_LABELS[t.lower()]
    words = re.sub(r"[-_]+", " ", t).strip()
    if words.isupper():
        words = words.lower()
    return words[:1].upper() + words[1:]


def _unclosed_code(text: str) -> int | None:
    """Index of the first backtick run that never closes, or None.

    A run of N backticks closes only on a later run of exactly N (CommonMark).
    """
    runs = [(m.start(), len(m.group())) for m in re.finditer(r"`+", text)]
    k = 0
    while k < len(runs):
        close = next((j for j in range(k + 1, len(runs)) if runs[j][1] == runs[k][1]), None)
        if close is None:
            return runs[k][0]
        k = close + 1
    return None


def _cut_before_open_code(text: str) -> str:
    """Drop a code span a clamp cut in half, so no stray backtick shows.

    Cutting before the span keeps it whole for the overflow; if nothing
    would be left, the backticks go instead.
    """
    k = _unclosed_code(text)
    if k is None:
        return text
    return text[:k].rstrip() or text.replace("`", "")


def clamp_words(text: str, limit: int = HEADLINE_MAX_WORDS) -> tuple[str, str]:
    """Shorten to `limit` words for display, preferring a sentence or ' — ' break.

    Returns (short, overflow). The overflow is shown in the item's note.
    """
    words = text.split()
    if len(words) <= limit:
        return text, ""
    norm = " ".join(words)
    head = " ".join(words[:limit])
    cut = -1
    for m in re.finditer(r"(?<=[.!?])\s| — ", head):
        cut = m.start()
    # Only use a break that keeps a meaningful first chunk.
    short = head[:cut] if cut > len(head) // 3 else head
    short = _cut_before_open_code(short)
    rest = norm[len(short):].lstrip(" —")
    return short.rstrip(" .,;:—") + "…", rest


def clamp_chars(text: str, limit: int = TITLE_MAX_CHARS) -> str:
    """Shorten a title for display: first sentence if it fits, else cut on a word."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t
    m = re.match(r"(.+?[.!?])(?:\s|$)", t)
    if m and len(m.group(1)) <= limit and _unclosed_code(m.group(1)) is None:
        return m.group(1).rstrip(".")
    cut = _cut_before_open_code(t[: limit + 1].rsplit(" ", 1)[0])
    return cut.rstrip(" .,;:—-") + "…"


def strip_links(text: str) -> str:
    """`[text](url)` becomes `text`: the page shows words, not link markup."""
    return _LINK_RE.sub(r"\1", text)


def plain(text: str) -> str:
    """Text with markdown markup removed and whitespace collapsed to one line."""
    text = strip_links(_LINE_MARK_RE.sub("", _COMMENT_RE.sub("", text)))
    return " ".join(_EMPH_RE.sub("", text).split())


def inline_html(text: str) -> Markup:
    # quote=True (the default): Markup is trusted wherever it lands,
    # including inside an attribute.
    out = html.escape(text)
    # A run of N backticks closes only on a run of exactly N (CommonMark), so
    # ``code`` with doubled backticks doesn't leave strays on each side.
    out = re.sub(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", r"<code>\2</code>", out)
    return Markup(out)


def highlight(text: str, needle: str, case_sensitive: bool) -> Markup:
    flags = 0 if case_sensitive else re.IGNORECASE
    parts = re.split(f"({re.escape(needle)})", text, flags=flags)
    out = []
    for k, part in enumerate(parts):
        esc = html.escape(part)
        out.append(f"<mark>{esc}</mark>" if k % 2 else esc)
    return Markup("".join(out))


def _title_from_slug(slug: str) -> str:
    # Short words are usually initialisms: "ai" -> "AI", "va" -> "VA".
    return " ".join(w.upper() if len(w) <= 2 else w.capitalize()
                    for w in slug.split("-"))


def display_name(project: Project) -> str:
    for path in (project.changelog_path, project.backlog_path):
        name = h1_name(path)
        if name:
            # An H1 that is just the folder name gets title-cased; any other
            # H1 (including a deliberate brand spelling like ATTRACTOR) wins.
            return _title_from_slug(project.slug) if name == project.slug else name
    return _title_from_slug(project.slug)
