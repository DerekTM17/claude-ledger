"""The writing rules for everything a person reads in ledger.

One copy, enforced at every write path (CLI and web forms) and printed by
`ledger rules` for AI tools to read before writing. Limits come from the
readability spec.
Never loosen a limit to make text fit; rewrite the text. Same stance as
ATTRACTOR's reading-level gate, whose formula fk_grade() copies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TITLE_MAX_CHARS = 70
WHY_MAX_WORDS = 60
WHY_MAX_SENTENCES = 3
WHY_MAX_GRADE = 9.0
HEADLINE_MAX_WORDS = 25
NOTE_MAX_WORDS = 80
TAG_MAX_CHARS = 20

# camelCase product names that read as ordinary words.
CAMEL_ALLOWLIST = frozenset({"iPhone", "iPad", "iOS", "macOS", "iCloud", "eBay"})

FIELD_NAMES = {"title": "Title", "why": "Why", "headline": "Headline", "note": "Note", "tag": "Tag"}
# A tag becomes `**[tag]**` in the file and a chip on the page: one short word.
_TAG_RE = re.compile(rf"[A-Za-z0-9-]{{1,{TAG_MAX_CHARS}}}")


@dataclass(frozen=True)
class Problem:
    field: str
    message: str


class RuleViolation(Exception):
    """Raised by writer functions before anything is written."""

    def __init__(self, problems: list[Problem]):
        self.problems = list(problems)
        super().__init__("\n".join(p.message for p in self.problems))


_URL_RE = re.compile(r"https?://\S+")
_CODE_EXT = r"(?:py|js|mjs|cjs|ts|tsx|jsx|md|json|ya?ml|toml|html|css|sh|sql|ini|cfg|env|lock|txt)"
_CAMEL_RE = re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b")
# Order matters: earlier patterns claim their text first, so one snippet is
# reported once (backticks before file names before snake_case, and so on).
_CODE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"`[^`\n]*`?"), "{hit} uses backticks. Describe it in words instead."),
    (re.compile(r"(?<![\w-])--[a-z][\w-]*"), "{hit} is a command-line flag. Leave it out."),
    (re.compile(rf"\b[\w./-]*\w\.{_CODE_EXT}\b"), "{hit} is a file name. Say what it does, or leave it out."),
    (re.compile(r"(?<![\w/])(?:~|\.\.?)?/[\w.-]+(?:/[\w.-]+)+|\b[\w-]+/[\w.-]+/[\w./-]+"),
     "{hit} is a file path. Say what it is, or leave it out."),
    (re.compile(r"\b[A-Za-z_]\w*(?:\.\w+)*\(\)"), "{hit} is a function name. Describe what it does instead."),
    (re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b"), "{hit} is a code name. Use plain words."),
    (re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"), "{hit} is a code name. Use plain words."),
    (_CAMEL_RE, "{hit} is a code name. Use plain words."),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"),
     "{hit} looks like a commit hash. It belongs in the commit message."),
    (re.compile(r"\b(?:PR|pull request|issue)\s*#?\d+\b|(?<![\w&])#\d{2,}\b", re.IGNORECASE),
     "{hit} is a PR or issue number. It belongs in the commit message."),
]


def _code_problems(text: str, field: str) -> list[Problem]:
    work = _URL_RE.sub(lambda m: " " * len(m.group(0)), text)
    problems: list[Problem] = []
    for rx, msg in _CODE_PATTERNS:
        hits = [m for m in rx.finditer(work)
                if not (rx is _CAMEL_RE and m.group(0) in CAMEL_ALLOWLIST)]
        for m in hits:
            problems.append(Problem(field, f"{FIELD_NAMES[field]}: " + msg.format(hit=f'"{m.group(0)}"')))
        for m in reversed(hits):  # blank claimed text so later patterns skip it
            work = work[:m.start()] + " " * (m.end() - m.start()) + work[m.end():]
    return problems


def _syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    n = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and n > 1 and not word.endswith(("le", "ee", "ye")):
        n -= 1
    return max(n, 1)


def fk_grade(text: str) -> float:
    """Flesch-Kincaid grade, as in ATTRACTOR's scripts/reading-level.py.

    Numbers become a one-syllable word so exact figures don't raise the grade.
    """
    text = re.sub(r"\$?\d[\d.,]*[%MKBmkb]?", "ten", text)
    sents = [s for s in re.split(r"[.!?:]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not sents or not words:
        return 0.0
    syl = sum(_syllables(w) for w in words)
    return 0.39 * (len(words) / len(sents)) + 11.8 * (syl / len(words)) - 15.59


_DOTTED_ABBR_RE = re.compile(r"^(?:[A-Za-z]{1,3}\.){2,}$")
_MONTH_ABBR = frozenset({"Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec"})
_SINGLE_LETTER_RE = re.compile(r"^[A-Z]\.$")


def _sentences(text: str) -> int:
    """Count sentences, handling abbreviations correctly.

    - "e.g.", "i.e.", "etc." end a sentence only when followed by whitespace
      and uppercase/digit/quote; followed by lowercase they don't.
    - Titles and prepositions "Mr.", "Mrs.", "Ms.", "Dr.", "St.", "vs.", "approx."
      never end a sentence.
    - Dotted abbreviations and bill numbers ("U.S.", "H.R.", "H.J.Res.",
      "S.Con.Res.") never end a sentence unless they end the text: the period
      ends one when the text since the last whitespace has an earlier period
      and is built of 1-3-letter segments each followed by a period.
    - A single uppercase letter, or a month abbreviation (Jan, Feb, Mar, Apr,
      Jun, Jul, Aug, Sep, Sept, Oct, Nov, Dec), followed by "." then
      whitespace then a digit is a citation, not a sentence end ("S. 5",
      "Aug. 28"). A single letter before anything else keeps the normal rule.
    - Every other . ! ? followed by whitespace or end of text ends a sentence.
    """
    count = 0

    i = 0
    while i < len(text):
        if text[i] in ".!?":
            punct = text[i]

            # Get text after punctuation
            rest = text[i + 1 :]

            # ! and ? always end sentences if followed by space or end
            if punct != ".":
                if not rest or rest[0].isspace():
                    count += 1
                i += 1
                continue

            # For periods, check what comes before
            before = text[:i]

            # Check if it's a title/preposition abbreviation (never ends sentence)
            if re.search(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|approx)$", before):
                i += 1
                continue

            # Check if it's a short abbreviation with special rules
            if re.search(r"\b(?:e\.g|i\.e|etc)$", before):
                # These end a sentence if followed by space + [A-Z0-9"] or end of string
                if not rest:
                    count += 1
                elif rest[0].isspace():
                    if len(rest) > 1 and (rest[1].isupper() or rest[1].isdigit() or rest[1] in ('"', "'")):
                        count += 1
                i += 1
                continue

            # Token since the last whitespace, ending at this period (inclusive).
            token = re.search(r"\S+$", text[: i + 1]).group(0)

            # Bill numbers and dotted abbreviations never end a sentence unless
            # they end the text.
            if _DOTTED_ABBR_RE.match(token):
                if not rest:
                    count += 1
                i += 1
                continue

            # "S. 5" and "Aug. 28" are citations, not sentence ends.
            next_is_digit = len(rest) > 1 and rest[0].isspace() and rest[1].isdigit()
            if next_is_digit and (_SINGLE_LETTER_RE.match(token) or token[:-1] in _MONTH_ABBR):
                i += 1
                continue

            # Regular period: ends sentence if followed by space or end
            if not rest or rest[0].isspace():
                count += 1

        i += 1

    return count


def check_entry(title: str | None, why: str | None) -> list[Problem]:
    """Problems with a changelog entry. Empty list means it can be written."""
    p: list[Problem] = []
    t = (title or "").strip()
    w = (why or "").strip()
    if not t:
        p.append(Problem("title", f"Title: it's empty. Say what changed in {TITLE_MAX_CHARS} characters or fewer."))
    else:
        # splitlines(), not "\n": a bare \r is also a line break in the file.
        if len(t.splitlines()) > 1:
            p.append(Problem("title", "Title: keep it to one line."))
        if len(t) > TITLE_MAX_CHARS:
            p.append(Problem("title", f"Title: it's {len(t)} characters. Keep it to {TITLE_MAX_CHARS} or fewer."))
        p += _code_problems(t, "title")
    if not w:
        p.append(Problem("why", f"Why: it's empty. Add up to {WHY_MAX_SENTENCES} short sentences on why this matters."))
    else:
        n, s, g = len(w.split()), _sentences(w), fk_grade(w)
        if s > WHY_MAX_SENTENCES:
            p.append(Problem("why", f"Why: it has {s} sentences. Use {WHY_MAX_SENTENCES} or fewer."))
        if n > WHY_MAX_WORDS:
            p.append(Problem("why", f"Why: it's {n} words. Keep it to {WHY_MAX_WORDS} or fewer."))
        if g > WHY_MAX_GRADE:
            p.append(Problem("why", f"Why: it reads at grade {g:.1f}. Aim for {WHY_MAX_GRADE:g} or below: "
                                    "shorter sentences and everyday words."))
        p += _code_problems(w, "why")
    return p


def check_item(headline: str | None, note: str | None = None,
               tag: str | None = None) -> list[Problem]:
    """Problems with a backlog item. The note may contain code; the headline may not."""
    p: list[Problem] = []
    h = (headline or "").strip()
    if not h:
        p.append(Problem("headline", "Headline: it's empty. Say what needs doing in plain words."))
    else:
        if len(h.splitlines()) > 1:
            p.append(Problem("headline", "Headline: keep it to one line. Put detail in a note."))
        n = len(h.split())
        if n > HEADLINE_MAX_WORDS:
            p.append(Problem("headline", f"Headline: it's {n} words. Keep it to {HEADLINE_MAX_WORDS} or fewer "
                                         "and put the detail in a note."))
        p += _code_problems(h, "headline")
    if note and len(note.split()) > NOTE_MAX_WORDS:
        p.append(Problem("note", f"Note: it's {len(note.split())} words. Keep it to {NOTE_MAX_WORDS} or fewer."))
    if tag and not _TAG_RE.fullmatch(tag):
        p.append(Problem("tag", f"Tag: use one short word, like bug or tech-debt: letters, numbers "
                                f"and dashes, up to {TAG_MAX_CHARS} characters."))
    return p


RULES_TEXT = f"""\
Ledger writing rules
====================
People who don't write code read ledger. Write every changelog entry and
backlog headline so they can follow it. Ledger checks these rules and refuses
text that breaks them. Fix the text and run the command again.

Changelog entries: ledger ship <project> "Title" --why "Why"
- Title: what changed for the person using the project, not what code
  changed. One line, {TITLE_MAX_CHARS} characters or fewer.
- Why: why it matters. {WHY_MAX_SENTENCES} short sentences or fewer, {WHY_MAX_WORDS} words or fewer,
  reading grade {WHY_MAX_GRADE:g} or below.
- One entry per outcome, not per commit. Skip typo fixes, formatting and
  changes nobody can see.

Backlog items: ledger idea <project> "Headline" --note "Detail"
- Headline: the task in plain words, {HEADLINE_MAX_WORDS} words or fewer.
- Note (optional): working detail for whoever picks it up, {NOTE_MAX_WORDS} words or
  fewer. Code names and file paths are fine here, and only here.
- Finished an item? Run: ledger done <project> "words from its headline"
  It moves to the Done list. Never edit BACKLOG.md or CHANGELOG.md by hand.

No code in titles, Whys or headlines
- No backticks, file names or paths, function or variable names, commit
  hashes, command-line flags, or PR and issue numbers.
- Numbers, money, percentages, dates and product names are fine.
- Technical detail belongs in the commit message. That is for developers.

Examples
  Bad:  Lock state.json + clear v1-review backlog
  Good: Sessions can no longer overwrite each other's records
  Why:  Two sessions saving at once could erase each other's notes. Now they
        take turns.

  Bad:  Reviewed and merged the first Opus 5 bill-text analyses batch (PR #92, 12 bills)
  Good: Checked and published the first bill analyses from the new model
  Why:  All 12 analyses were checked against the bill text. One made a claim
        the bill does not support, so we removed it before publishing.
"""
