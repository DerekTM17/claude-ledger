from datetime import date
from pathlib import Path

from ledger import display
from ledger.models import Project

TODAY = date(2026, 9, 17)


def test_relative_date():
    rd = display.relative_date
    assert rd("2026-09-17", TODAY) == "today"
    assert rd("2026-09-18", TODAY) == "today"          # future clamps to today
    assert rd("2026-09-16", TODAY) == "yesterday"
    assert rd("2026-09-04", TODAY) == "13 days ago"
    assert rd("2026-09-03", TODAY) == "2 weeks ago"    # 14 days
    assert rd("2026-07-20", TODAY) == "8 weeks ago"    # 59 days
    assert rd("2026-07-19", TODAY) == "2 months ago"   # 60 days: weeks only under 9
    assert rd(None, TODAY) == ""
    assert rd("not-a-date", TODAY) == "not-a-date"


def test_status():
    assert display.status(None) == ("never", "Nothing shipped yet")
    assert display.status(0) == ("today", "Shipped today")
    assert display.status(7) == ("active", "Active this week")
    assert display.status(30) == ("recent", "Active this month")
    assert display.status(48) == ("quiet", "Quiet for 7 weeks")
    assert display.status(78) == ("quiet", "Quiet for 3 months")


def test_tag_label():
    assert display.tag_label("tech-debt") == "Cleanup"
    assert display.tag_label("feat") == "Feature"
    assert display.tag_label("state-aggregate") == "State aggregate"
    assert display.tag_label("HIGH") == "High"
    assert display.tag_label("data/quality") == "Data/quality"


def test_clamp_words_prefers_sentence_break():
    text = ("Fix the dashboard counts so finished work is not shown as open. "
            "This also covers nested items and every odd checkbox that the old code missed entirely today.")
    short, rest = display.clamp_words(text, 25)
    assert short == "Fix the dashboard counts so finished work is not shown as open…"
    assert rest.startswith("This also covers")


def test_clamp_words_short_text_untouched():
    assert display.clamp_words("Pick the domain name", 25) == ("Pick the domain name", "")


def test_clamp_words_hard_cut_when_no_break():
    text = " ".join(f"w{i}" for i in range(40))
    short, rest = display.clamp_words(text, 25)
    assert short == " ".join(f"w{i}" for i in range(25)) + "…"
    assert rest.split()[0] == "w25"


def test_clamp_chars():
    assert display.clamp_chars("Short title", 70) == "Short title"
    long = ("Reviewed and merged the first batch. Adversarial review by the method, "
            "with text re-fetched for all 12 bills and more.")
    assert display.clamp_chars(long, 70) == "Reviewed and merged the first batch"
    no_stop = "word " * 30
    out = display.clamp_chars(no_stop, 70)
    assert len(out) <= 71 and out.endswith("…")


def test_inline_html_escapes_and_codes():
    assert str(display.inline_html("use `a<b>` & go")) == "use <code>a&lt;b&gt;</code> &amp; go"


def test_inline_html_double_backtick_code():
    # RST-style ``code`` (seen in a real CHANGELOG) left a stray
    # backtick on each side.
    assert str(display.inline_html("as ``kind='x'`` rows")) == "as <code>kind=&#x27;x&#x27;</code> rows"
    assert str(display.inline_html("``a `b` c``")) == "<code>a `b` c</code>"


def test_highlight():
    assert str(display.highlight("Widget and widget", "widget", False)) == \
        "<mark>Widget</mark> and <mark>widget</mark>"
    assert str(display.highlight("Widget and widget", "Widget", True)) == \
        "<mark>Widget</mark> and widget"


def test_plain():
    assert display.plain("**Bold** ~~gone~~ `code`") == "Bold gone code"


def test_plain_drops_block_markup():
    # Search snippets come from raw note text; nested checkboxes, headings,
    # comments and link syntax must not show up as markup.
    note = ("### Sub head\nIntro line <!-- added 2026-09-01 -->\n"
            "- [ ] [ops] nested box\n  - [x] done child\n* star bullet\n"
            "1. numbered\nSee [the spec](docs/spec.md) and [ops] tags.")
    assert display.plain(note) == (
        "Sub head Intro line [ops] nested box done child star bullet "
        "numbered See the spec and [ops] tags.")


def test_display_name(tmp_path: Path):
    def proj(slug, h1=None):
        p = tmp_path / slug
        (p / "docs").mkdir(parents=True)
        if h1:
            (p / "docs" / "CHANGELOG.md").write_text(f"# {h1} — Changelog\n")
        return Project(slug=slug, path=p)
    assert display.display_name(proj("congressional-dashboard", "Congressional Dashboard")) == "Congressional Dashboard"
    assert display.display_name(proj("inflation-reality", "inflation-reality")) == "Inflation Reality"
    assert display.display_name(proj("netgraph-ai")) == "Netgraph AI"
    assert display.display_name(proj("va-dev-tracker")) == "VA Dev Tracker"
    assert display.display_name(proj("attractor", "ATTRACTOR")) == "ATTRACTOR"


def test_weeks_stop_before_nine():
    # Spec: "N weeks ago (under 9)". round() turned 60-62 days into "9 weeks".
    for n in range(14, 400):
        text = display.status(n)[1] if n > 30 else ""
        assert "9 weeks" not in text and "9 weeks" not in display.relative_date(
            date.fromordinal(TODAY.toordinal() - n).isoformat(), TODAY), n
    assert display.status(59) == ("quiet", "Quiet for 8 weeks")
    assert display.status(60) == ("quiet", "Quiet for 2 months")


def test_markup_escapes_quotes():
    # Markup is trusted wherever it lands, attributes included, so quotes
    # must be escaped too.
    assert "&quot;" in str(display.inline_html('say "hi"'))
    assert '"' not in str(display.inline_html('say "hi"'))
    assert '"' not in str(display.highlight('say "hi" now', "hi", False))


def test_clamp_never_splits_a_code_span():
    words = " ".join(f"w{i}" for i in range(24))
    short, rest = display.clamp_words(words + " `make release` then more words", 25)
    assert "`" not in short and rest.startswith("`make release`")
    title = "Speed up the nightly build by moving the slow step into `make release-all` today"
    out = display.clamp_chars(title, 70)
    assert out.count("`") % 2 == 0 and out.endswith("…"), out


def test_clamp_defaults_follow_the_rules():
    import inspect
    from ledger import rules
    assert inspect.signature(display.clamp_words).parameters["limit"].default == rules.HEADLINE_MAX_WORDS
    assert inspect.signature(display.clamp_chars).parameters["limit"].default == rules.TITLE_MAX_CHARS
