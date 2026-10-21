import pytest

from ledger.markdown import most_recent_changelog_entry, backlog_counts, MarkdownStructureError, SubsectionNotFoundError


def test_most_recent_entry_returns_latest_date_and_first_h3(tmp_project):
    date, title = most_recent_changelog_entry(tmp_project.changelog_path)
    assert date == "2026-05-10"
    assert title == "Second feature shipped"


def test_most_recent_entry_returns_none_when_no_dates(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("# Project\n\nIntro only, no entries.\n")
    assert most_recent_changelog_entry(f) is None


def test_most_recent_entry_returns_none_when_file_missing(tmp_path):
    assert most_recent_changelog_entry(tmp_path / "missing.md") is None


def test_backlog_counts_groups_by_horizon(tmp_project):
    counts = backlog_counts(tmp_project.backlog_path)
    assert counts == {"now": 2, "soon": 2, "someday": 2}


def test_backlog_counts_tolerates_plain_tag_form(tmp_project):
    # Someday contains "- [ ] [perf] Old-format plain-tag item..." (no bold).
    # The reader counts checkboxes regardless of tag format.
    counts = backlog_counts(tmp_project.backlog_path)
    assert counts["someday"] == 2


def test_backlog_counts_returns_zeros_when_file_missing(tmp_path):
    counts = backlog_counts(tmp_path / "missing.md")
    assert counts == {"now": 0, "soon": 0, "someday": 0}


def test_backlog_counts_ignores_unknown_h2_sections(tmp_path):
    f = tmp_path / "BACKLOG.md"
    f.write_text(
        "# X\n\n## Now\n- [ ] one\n\n## Bogus\n- [ ] noise\n\n## Soon\n- [ ] two\n"
    )
    assert backlog_counts(f) == {"now": 1, "soon": 1, "someday": 0}


from ledger.markdown import ship


def test_ship_prepends_new_date_block_before_existing(tmp_project):
    before = tmp_project.changelog_path.read_text()
    ship(tmp_project.changelog_path, today="2026-05-18", title="New thing")
    after = tmp_project.changelog_path.read_text()
    # New date appears before 2026-05-10
    new_idx = after.index("## 2026-05-18")
    old_idx = after.index("## 2026-05-10")
    assert new_idx < old_idx
    assert "### New thing" in after
    # Existing content (everything from old `## 2026-05-10` onward) is byte-identical
    assert after[after.index("## 2026-05-10"):] == before[before.index("## 2026-05-10"):]


def test_ship_with_why_includes_why_paragraph(tmp_project):
    ship(tmp_project.changelog_path, today="2026-05-18", title="X", why="because Z")
    after = tmp_project.changelog_path.read_text()
    assert "**Why:** because Z" in after


def test_ship_appends_h3_under_existing_today(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(
        "# Proj — Changelog\n\nIntro.\n\n"
        "## 2026-05-18\n\n### First today\n\n**What:** X\n\n"
        "## 2026-05-10\n\n### Old\n\n**What:** Y\n"
    )
    before = f.read_text()
    ship(f, today="2026-05-18", title="Second today")
    after = f.read_text()
    # New H3 appears under existing today header, before "First today"
    second_idx = after.index("### Second today")
    first_idx = after.index("### First today")
    assert second_idx < first_idx
    # The old date block (## 2026-05-10 onward) is unchanged byte-for-byte
    assert after[after.index("## 2026-05-10"):] == before[before.index("## 2026-05-10"):]


def test_ship_no_existing_dates_appends_after_intro(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("# Proj — Changelog\n\nIntro paragraph.\n")
    ship(f, today="2026-05-18", title="First ever")
    after = f.read_text()
    assert "Intro paragraph." in after
    assert "## 2026-05-18" in after
    assert "### First ever" in after
    # Intro precedes the new date block
    assert after.index("Intro paragraph.") < after.index("## 2026-05-18")


def test_ship_lazy_creates_changelog(empty_project):
    path = empty_project.changelog_path
    assert not path.exists()
    ship(path, today="2026-05-18", title="Hello", project_name="Empty Project")
    assert path.exists()
    content = path.read_text()
    assert content.startswith("# Empty Project — Changelog")
    assert "## 2026-05-18" in content
    assert "### Hello" in content


def test_ship_creates_parent_docs_dir(empty_project):
    # docs/ doesn't exist yet
    assert not empty_project.docs_dir.exists()
    ship(empty_project.changelog_path, today="2026-05-18", title="X",
         project_name="Empty Project")
    assert empty_project.docs_dir.is_dir()
    assert empty_project.changelog_path.is_file()


from ledger.markdown import idea


def test_idea_appends_to_soon_by_default(tmp_project):
    before = tmp_project.backlog_path.read_text()
    idea(tmp_project.backlog_path, text="new soon item", today="2026-05-18",
         section="Soon")
    after = tmp_project.backlog_path.read_text()
    assert "- [ ] new soon item <!-- added 2026-05-18 -->" in after
    # Item is inside the Soon block (before "## Someday")
    new_idx = after.index("new soon item")
    someday_idx = after.index("## Someday")
    soon_idx = after.index("## Soon")
    assert soon_idx < new_idx < someday_idx
    # Now-section content unchanged
    assert after[:after.index("## Soon")] == before[:before.index("## Soon")]


def test_idea_with_tag_uses_bold_format(tmp_project):
    idea(tmp_project.backlog_path, text="something", today="2026-05-18",
         section="Soon", tag="feat")
    after = tmp_project.backlog_path.read_text()
    assert "- [ ] **[feat]** something <!-- added 2026-05-18 -->" in after


def test_idea_appends_to_now_section(tmp_project):
    idea(tmp_project.backlog_path, text="urgent thing", today="2026-05-18",
         section="Now")
    after = tmp_project.backlog_path.read_text()
    new_idx = after.index("urgent thing")
    soon_idx = after.index("## Soon")
    assert new_idx < soon_idx


def test_idea_appends_to_someday_section(tmp_project):
    idea(tmp_project.backlog_path, text="latent thing", today="2026-05-18",
         section="Someday")
    after = tmp_project.backlog_path.read_text()
    assert "latent thing" in after
    new_idx = after.index("latent thing")
    someday_idx = after.index("## Someday")
    assert new_idx > someday_idx


def test_idea_with_subsection_targets_h3(tmp_project):
    idea(tmp_project.backlog_path, text="strategic add", today="2026-05-18",
         section="Soon", sub_section="Strategic")
    after = tmp_project.backlog_path.read_text()
    strategic_idx = after.index("### Strategic")
    new_idx = after.index("strategic add")
    docs_idx = after.index("### Documentation")
    assert strategic_idx < new_idx < docs_idx


def test_idea_subsection_missing_raises(tmp_project):
    with pytest.raises(SubsectionNotFoundError):
        idea(tmp_project.backlog_path, text="nope", today="2026-05-18",
             section="Soon", sub_section="DoesNotExist")


def test_idea_missing_horizon_section_raises(tmp_path):
    f = tmp_path / "BACKLOG.md"
    f.write_text("# Proj — Backlog\n\n(no sections)\n")
    with pytest.raises(MarkdownStructureError) as exc:
        idea(f, text="x", today="2026-05-18", section="Soon")
    assert "## Soon" in str(exc.value)


def test_idea_lazy_creates_backlog(empty_project):
    idea(empty_project.backlog_path, text="first ever", today="2026-05-18",
         section="Soon", project_name="Empty Project")
    content = empty_project.backlog_path.read_text()
    assert content.startswith("# Empty Project — Backlog")
    assert "## Now" in content
    assert "## Soon" in content
    assert "## Someday" in content
    assert "first ever" in content
    assert "Suggested tags:" in content


def test_ship_strips_bom_on_read_and_does_not_write_it(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text("﻿# Proj — Changelog\n\nIntro.\n", encoding="utf-8")
    ship(f, today="2026-05-18", title="X")
    raw_bytes = f.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "BOM was preserved (should be stripped)"


def test_ship_normalizes_crlf_to_lf(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_bytes(b"# Proj\r\n\r\nIntro.\r\n")
    ship(f, today="2026-05-18", title="X")
    raw = f.read_bytes()
    assert b"\r\n" not in raw, "CRLF survived first write"


def test_writes_end_with_trailing_newline(tmp_project):
    ship(tmp_project.changelog_path, today="2026-05-18", title="x")
    assert tmp_project.changelog_path.read_bytes().endswith(b"\n")
    idea(tmp_project.backlog_path, text="y", today="2026-05-18", section="Soon")
    assert tmp_project.backlog_path.read_bytes().endswith(b"\n")


from ledger.markdown import grep_file


def test_grep_returns_matching_lines_with_numbers(tmp_project):
    hits = grep_file(tmp_project.backlog_path, "urgent thing", case_sensitive=False)
    assert len(hits) == 1
    line_no, line_text = hits[0]
    assert line_no > 0
    assert "urgent thing" in line_text.lower()


def test_grep_case_sensitive_distinguishes(tmp_project):
    upper = grep_file(tmp_project.backlog_path, "URGENT", case_sensitive=True)
    lower = grep_file(tmp_project.backlog_path, "URGENT", case_sensitive=False)
    assert upper == []
    assert len(lower) == 1


def test_grep_missing_file_returns_empty(tmp_path):
    assert grep_file(tmp_path / "missing.md", "x") == []


def test_backlog_counts_ignore_done_and_nested(tmp_path):
    from ledger.markdown import backlog_counts
    p = tmp_path / "BACKLOG.md"
    p.write_text(
        "# X — Backlog\n\n## Now\n- [ ] open one\n- [x] done one\n"
        "- [ ] ~~struck~~ — DONE 2026-07-01\n- [ ] parent\n  - [ ] nested child\n"
        "- [~] partly done\n\n## Soon\n- [→] moved\n- [ ] later\n\n## Someday\n"
    )
    assert backlog_counts(p) == {"now": 3, "soon": 1, "someday": 0}


def test_idea_inserts_after_last_item_not_after_footer(tmp_path):
    from ledger.markdown import idea
    p = tmp_path / "BACKLOG.md"
    p.write_text(
        "# X — Backlog\n\n## Now\n\n## Soon\n\n## Someday\n\nLatent items.\n\n"
        "- [ ] existing <!-- added 2026-05-19 -->\n\n"
        "<!-- Suggested tags: bug, feat -->\n"
    )
    idea(p, text="new one", today="2026-09-17", section="Someday")
    lines = p.read_text().splitlines()
    assert lines.index("- [ ] new one <!-- added 2026-09-17 -->") == \
        lines.index("- [ ] existing <!-- added 2026-05-19 -->") + 1
    assert lines[-1] == "<!-- Suggested tags: bug, feat -->"


def test_idea_empty_section_goes_before_trailing_comment(tmp_path):
    from ledger.markdown import idea
    p = tmp_path / "BACKLOG.md"
    p.write_text(
        "# X — Backlog\n\n## Now\n\n## Soon\n\n## Someday\n\nLatent items.\n\n"
        "<!-- Suggested tags: bug, feat -->\n"
    )
    idea(p, text="first", today="2026-09-17", section="Someday")
    text = p.read_text()
    assert text.index("- [ ] first") < text.index("<!-- Suggested tags")


def test_idea_after_multiline_item_keeps_its_body(tmp_path):
    from ledger.markdown import idea
    p = tmp_path / "BACKLOG.md"
    p.write_text("# X — Backlog\n\n## Now\n- [ ] parent\n  continued\n  - child\n\n## Soon\n\n## Someday\n")
    idea(p, text="second", today="2026-09-17", section="Now")
    assert "- [ ] parent\n  continued\n  - child\n- [ ] second <!-- added 2026-09-17 -->\n" in p.read_text()


def test_idea_with_note_indents_it(tmp_path):
    from ledger.markdown import idea
    from ledger.parse import parse_backlog
    p = tmp_path / "BACKLOG.md"
    p.write_text("# X — Backlog\n\n## Now\n\n## Soon\n\n## Someday\n")
    idea(p, text="Headline", today="2026-09-17", section="Now",
         tag="feat", note="Detail one.\nSee `config.js`.")
    assert "- [ ] **[feat]** Headline <!-- added 2026-09-17 -->\n  Detail one.\n  See `config.js`.\n" in p.read_text()
    [it] = parse_backlog(p)
    assert it.note == "Detail one.\nSee `config.js`."


def test_render_text_is_safe():
    from ledger.markdown import render_text
    out = render_text("**b** <script>x</script>")
    assert "<strong>b</strong>" in out and "<script>" not in out


LATER_CL = (
    "# Alpha — Changelog\n\n"
    "## 2026-09-10 (later)\n\n### Later same-day fix\n\n**Why:** It came late.\n\n"
    "## 2026-09-10\n\n### Morning work\n\n**Why:** It came early.\n\n"
    "## 2026-09-01\n\n### Older work\n"
)


def test_most_recent_entry_reads_a_suffixed_date_header(tmp_path):
    # A `## 2026-09-10 (later)` block on top is the newest entry, the same one
    # the dashboard shows; the exact-header match used to skip past it.
    f = tmp_path / "CHANGELOG.md"
    f.write_text(LATER_CL)
    assert most_recent_changelog_entry(f) == ("2026-09-10", "Later same-day fix")


def test_ship_puts_new_date_block_above_a_suffixed_date_header(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(LATER_CL)
    ship(f, today="2026-09-17", title="New thing")
    after = f.read_text()
    assert after.index("## 2026-09-17\n") < after.index("## 2026-09-10 (later)")
    assert after.endswith(LATER_CL[LATER_CL.index("## 2026-09-10 (later)"):])


def test_new_file_templates_match_the_rules():
    # A new project's files point at the commands, not at hand edits or the
    # old What/Why/Tradeoffs entry shape the rules no longer use.
    from ledger.markdown import BACKLOG_TEMPLATE, CHANGELOG_TEMPLATE
    backlog = BACKLOG_TEMPLATE.format(name="alpha")
    changelog = CHANGELOG_TEMPLATE.format(name="alpha")
    for cmd in ("ledger idea", "ledger done", "ledger rules"):
        assert cmd in backlog
    for cmd in ("ledger ship", "ledger rules"):
        assert cmd in changelog
    assert "by hand" not in backlog
    assert "What" not in changelog and "Tradeoffs" not in changelog
    for h in ("## Now", "## Soon", "## Someday"):
        assert f"\n{h}\n" in backlog
