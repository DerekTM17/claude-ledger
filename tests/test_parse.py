from pathlib import Path

from ledger.parse import (
    h1_name, item_end, parse_backlog, parse_changelog, parse_done,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


BACKLOG = """\
# Congressional Dashboard — Backlog

Open work organized by horizon (Now / Soon / Someday) with `[tag]` for
domain.

## Now

MVP launched 2026-06-29.
Remaining near-term items:

### Post-launch
- [x] **[ops]** ~~activate data freshness~~ — DONE 2026-07-01. Volume set. <!-- added 2026-06-30 -->
- [ ] **[ops]** ~~one-time Senate backfill~~ — DONE 2026-07-01. Full backfill. <!-- added 2026-06-30 -->
- [ ] **[feat]** create the public Google Form and paste its URL <!-- added 2026-06-29 -->
- [ ] [bug] 24.1% of rows are duplicates — dedupe on key <!-- added 2026-08-01 --> <!-- closed 2026-08-26 -->
- [~] **[enrichment] NJ coverage gap closure — substantially shipped.** rest of line
- [ ] **[a][b] Bold lead sentence.** then more text <!-- added 2026-08-03 --> **DONE 2026-08-04**: tail
- [ ] plain item with a multi-line comment <!-- done 2026-07-16, merged
  eab7f37; plan.md -->
- [ ] wrapped item first line
  continues here with more words
  - plain sub-bullet
  - [ ] nested checkbox is part of the note

  **Follow-ups (none blocking):**
  - [x] nested done child
- [ ] next item after a blank-separated body

## Soon

### Security & auth

#### HIGH — pre-production hardening
- [ ] **[HIGH][security] Environment-aware debug default.** <!-- added 2026-06-01 -->
- [→] **Review Queue: Map action** — PROMOTED elsewhere

## Someday

<!-- Suggested tags: bug, feat, perf -->
- [ ] ~~**[BUG][data] AZ ASRS stale**~~ — original text retained
- [ ] ~~[ops] quota ~~ **CLOSED 2026-08-26 — resolved**
- [ ] **DONE 2026-07-09: [sales/data-trust] Accounting basis surfaced**

---

*Conventions: `[tag]` is one of: bug, feat.*
- [ ] item after the footer
"""


def test_backlog_sections_and_counts(tmp_path):
    items = parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))
    by = {s: [i for i in items if i.section == s] for s in ("Now", "Soon", "Someday")}
    assert len(by["Now"]) == 9
    assert len(by["Soon"]) == 2
    assert len(by["Someday"]) == 4  # includes the item after the footer


def test_nested_checkboxes_are_not_items(tmp_path):
    items = parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))
    assert not any("nested" in i.headline for i in items)
    wrapped = next(i for i in items if i.headline.startswith("wrapped item"))
    assert "continues here" in wrapped.note
    assert "- [ ] nested checkbox is part of the note" in wrapped.note
    assert "nested done child" in wrapped.note  # blank line then indented = same item
    assert wrapped.note.splitlines()[0] == "continues here with more words"  # dedented


def test_done_detection(tmp_path):
    items = {i.headline[:25]: i for i in parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))}
    done = {k for k, i in items.items() if i.done}
    assert "activate data freshness —" in done          # [x]
    assert "one-time Senate backfill " in done          # [ ] + struck title + DONE
    assert "Review Queue: Map action " in done          # [→]
    assert "AZ ASRS stale — original " in done          # struck title, tags inside strike
    assert "quota CLOSED 2026-08-26 —" in done          # struck title + CLOSED
    assert "create the public Google " not in done
    assert "NJ coverage gap closure —" not in done       # [~] is partly done = open
    assert "Bold lead sentence. then " not in done       # DONE word mid-line keeps it open


def test_tags_added_and_headline_cleanup(tmp_path):
    items = parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))
    form = next(i for i in items if "Google Form" in i.headline)
    assert form.tags == ["feat"]
    assert form.added == "2026-06-29"
    assert form.headline == "create the public Google Form and paste its URL"
    dup = next(i for i in items if "duplicates" in i.headline)
    assert dup.tags == ["bug"]
    assert "<!--" not in dup.headline and "closed" not in dup.headline
    lead = next(i for i in items if i.headline.startswith("Bold lead"))
    assert lead.tags == ["a", "b"]
    assert "**" not in lead.headline
    assert lead.added == "2026-08-03"
    status = next(i for i in items if "Accounting basis" in i.headline)
    assert status.tags == ["sales/data-trust"]
    assert status.headline == "Accounting basis surfaced"


def test_multiline_comment_is_opaque(tmp_path):
    items = parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))
    it = next(i for i in items if i.headline.startswith("plain item"))
    assert it.headline == "plain item with a multi-line comment"
    assert it.note == ""  # the comment's second line is not note text


def test_emphasis_open_at_line_end_carries_into_headline(tmp_path):
    # Real case (state-legislature BACKLOG-DONE.md): a hard-wrapped headline
    # opens **bold** and ~~strike~~ on line 1 and closes them on line 2.
    # Splitting at the line break leaked "vote event**~~" into the note.
    text = (
        "## Soon\n\n"
        "- [x] **[frontend]** ~~the tile says **\"Floor votes\" but counts every <!-- from Soon -->\n"
        "  vote event**~~ — RELABELLED \"Recorded votes\" 2026-07-26 (the\n"
        "  honest option).\n"
        "- [ ] **never closed bold on one line\n"
        "  second line stays in the note\n"
    )
    wrapped, unclosed = parse_backlog(_write(tmp_path, "BACKLOG.md", text))
    assert wrapped.headline == 'the tile says "Floor votes" but counts every vote event'
    assert wrapped.note == '— RELABELLED "Recorded votes" 2026-07-26 (the\nhonest option).'
    assert "**" not in wrapped.note and "~~" not in wrapped.note
    # No closer within reach: leave the split as it was.
    assert unclosed.headline == "never closed bold on one line"
    assert unclosed.note == "second line stays in the note"


def test_subsections(tmp_path):
    items = parse_backlog(_write(tmp_path, "BACKLOG.md", BACKLOG))
    assert items[0].subsection == "Post-launch"
    debug = next(i for i in items if "debug default" in i.headline)
    assert debug.subsection == "Security & auth › HIGH — pre-production hardening"
    assert debug.tags == ["HIGH", "security"]


def test_item_line_ranges_round_trip(tmp_path):
    p = _write(tmp_path, "BACKLOG.md", BACKLOG)
    lines = p.read_text().splitlines()
    for it in parse_backlog(p):
        assert "\n".join(lines[it.start:it.end]) == it.raw
        assert item_end(lines, it.start) == it.end


def test_missing_file_is_empty(tmp_path):
    assert parse_backlog(tmp_path / "nope.md") == []
    assert parse_changelog(tmp_path / "nope.md") == []
    assert parse_done(tmp_path / "nope.md") == []
    assert h1_name(tmp_path / "nope.md") is None


CHANGELOG = """\
# attractor — Changelog

Intro text.

## 2026-07-07 (later)

### Suffixed date entry

**Why:** Because suffixes happen.

## 2026-07-07

### What-first entry

**What:** Did the thing.

**Why:** It was needed
and this line was hard-wrapped.

**Tradeoffs / Alternatives considered:** Could have not.

- a bullet

### Why-label variant

**Why / caveat:** Variant label.

### Title only with a very long paragraph title. It keeps going (PR #92, 12 bills).

### No why at all

**What:** Only a what.

### Prose only

Three isolated fixes landed.

---

## 2026-06-03

### Dup

### Dup

**Why:** Second copy has the body.

## 2026-04-27 → 2026-05-12

### Range entry

**Why:** Ranges use the latest date.
"""


def test_changelog_dates_and_order(tmp_path):
    es = parse_changelog(_write(tmp_path, "CHANGELOG.md", CHANGELOG))
    assert [e.title for e in es] == [
        "Suffixed date entry", "What-first entry", "Why-label variant",
        "Title only with a very long paragraph title. It keeps going (PR #92, 12 bills).",
        "No why at all", "Prose only", "Dup", "Range entry",
    ]
    assert es[0].date == "2026-07-07"
    assert es[-1].date == "2026-05-12"


def test_changelog_why_and_more(tmp_path):
    es = {e.title: e for e in parse_changelog(_write(tmp_path, "CHANGELOG.md", CHANGELOG))}
    wf = es["What-first entry"]
    assert wf.why == "It was needed and this line was hard-wrapped."
    assert "**What:** Did the thing." in wf.more
    assert "**Tradeoffs / Alternatives considered:**" in wf.more
    assert "- a bullet" in wf.more
    assert "---" not in wf.more
    assert es["Why-label variant"].why == "Variant label."
    assert es["No why at all"].why == "Only a what."
    assert es["Prose only"].why == "Three isolated fixes landed."
    t = es["Title only with a very long paragraph title. It keeps going (PR #92, 12 bills)."]
    assert t.why == "" and t.more == ""


def test_changelog_duplicate_empty_h3_shown_once(tmp_path):
    es = [e for e in parse_changelog(_write(tmp_path, "CHANGELOG.md", CHANGELOG)) if e.title == "Dup"]
    assert len(es) == 1
    assert es[0].why == "Second copy has the body."


def test_h1_name(tmp_path):
    assert h1_name(_write(tmp_path, "CHANGELOG.md", CHANGELOG)) == "attractor"
    assert h1_name(_write(tmp_path, "B.md", BACKLOG)) == "Congressional Dashboard"
    assert h1_name(_write(tmp_path, "D.md", "# LinkHub — Done\n")) == "LinkHub"


def test_parse_done_groups_by_date(tmp_path):
    p = _write(tmp_path, "BACKLOG-DONE.md", """\
# X — Done

Finished backlog items. Newest first.

## 2026-09-17

- [x] **[bug]** fixed it <!-- from Now › Post-launch -->
  with a note

## 2026-09-01

- [x] older one <!-- from Soon -->
""")
    items = parse_done(p)
    assert [(i.section, i.headline) for i in items] == [
        ("2026-09-17", "fixed it"), ("2026-09-01", "older one")]
    assert items[0].note == "with a note"
