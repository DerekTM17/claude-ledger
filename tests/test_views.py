from datetime import date, timedelta
from pathlib import Path

from ledger import views
from ledger.models import Project

TODAY = date(2026, 9, 17)


def _proj(tmp_path: Path, slug: str, changelog: str | None, backlog: str | None,
          done: str | None = None) -> Project:
    p = tmp_path / slug
    (p / "docs").mkdir(parents=True)
    if changelog is not None:
        (p / "docs" / "CHANGELOG.md").write_text(changelog)
    if backlog is not None:
        (p / "docs" / "BACKLOG.md").write_text(backlog)
    if done is not None:
        (p / "docs" / "BACKLOG-DONE.md").write_text(done)
    return Project(slug=slug, path=p)


CL = """# Alpha — Changelog

## 2026-09-16

### Short title

**Why:** It matters.

**What:** Did `code_thing`.

## 2026-09-10

### A title-only paragraph that runs on well past the seventy character limit for sure. More text.
"""
BL = """# Alpha — Backlog

## Now

### Post-launch
- [ ] **[feat]** first open item <!-- added 2026-09-15 -->
  Note line with `config.js`.
- [x] finished item
- [ ] second item in a very long headline """ + "word " * 30 + """

## Soon
- [ ] soon thing

## Someday
- [ ] someday thing
"""


def test_dashboard_rows_and_summary(tmp_path):
    a = _proj(tmp_path, "alpha", CL, BL)
    b = _proj(tmp_path, "beta", None, None)
    d = views.dashboard([b, a], TODAY)
    assert [r["slug"] for r in d["rows"]] == ["alpha", "beta"]  # recency, never-shipped last
    r = d["rows"][0]
    assert r["name"] == "Alpha"
    assert (r["status_key"], r["status_label"]) == ("active", "Active this week")
    assert r["last_when"] == "yesterday"
    assert str(r["last_title"]) == "Short title"
    assert str(r["next_up"]) == "first open item"
    assert (r["now"], r["later"]) == (2, 2)
    assert "first open item" in r["search_text"]
    assert d["rows"][1]["status_label"] == "Nothing shipped yet"
    assert d["summary"] == {"projects": 2, "shipped_week": 1, "now_total": 2, "quiet": 0}


def test_project_view(tmp_path):
    a = _proj(tmp_path, "alpha", CL, BL, done="# Alpha — Done\n\n## 2026-09-01\n\n- [x] old done thing\n")
    v = views.project(a, TODAY)
    assert v["name"] == "Alpha" and v["now_count"] == 2 and v["later_count"] == 2
    [group] = v["up_next"]
    assert group["subsection"] == "Post-launch"
    first, second = group["items"]
    assert str(first["headline"]) == "first open item"
    assert first["tags"] == ["Feature"]
    assert first["added"] == "2 days ago"
    assert "<code>config.js</code>" in first["note_html"]
    assert str(second["headline"]).endswith("…")
    assert "word" in second["note_html"]                 # overflow moved into the note
    assert [str(i["headline"]) for i in v["later"]["Soon"]] == ["soon thing"]
    titles = [str(e["title"]) for e in v["finished"]]
    assert titles[0] == "Short title"
    # First sentence is 83 characters, so the display cuts on a word instead.
    assert titles[1] == "A title-only paragraph that runs on well past the seventy character…"
    assert "More text." in v["finished"][1]["more_html"]  # full old title kept in the fold
    assert "<code>code_thing</code>" in v["finished"][0]["more_html"]
    assert str(v["finished"][0]["why"]) == "It matters."
    done_heads = [str(i["headline"]) for i in v["done"]]
    assert done_heads == ["finished item", "old done thing"]   # un-tidied done items too


def test_search_groups(tmp_path):
    a = _proj(tmp_path, "alpha", CL, BL, done="# Alpha — Done\n\n## 2026-09-01\n\n- [x] old done needle\n")
    groups = views.search([a], "needle", False, TODAY)
    assert groups[0]["name"] == "Alpha"
    assert groups[0]["hits"][0]["kind"] == "Done"
    assert "<mark>needle</mark>" in str(groups[0]["hits"][0]["text"])
    g2 = views.search([a], "code_thing", False, TODAY)
    hit = g2[0]["hits"][0]
    assert hit["kind"] == "Finished" and str(hit["text"]) == "Short title"
    assert "<mark>code_thing</mark>" in str(hit["snippet"])
    assert views.search([a], "Short", True, TODAY) and not views.search([a], "SHORT", True, TODAY)


def test_search_hit_text_has_no_raw_backticks(tmp_path):
    # Headlines keep `code` for the project page; a search hit is plain
    # highlighted text, so the backticks showed as-is.
    a = _proj(tmp_path, "alpha", "# Alpha — Changelog\n\n## 2026-09-16\n\n### Set `docs_url` off\n",
              "# Alpha — Backlog\n\n## Now\n- [ ] gate `FastAPI(docs_url=None)` in prod\n")
    hits = views.search([a], "docs_url", False, TODAY)[0]["hits"]
    assert len(hits) == 2
    for h in hits:
        assert "`" not in str(h["text"]) and "<mark>docs_url</mark>" in str(h["text"])


LINK_CL = """# Alpha — Changelog

## 2026-09-16

### See [the notes](https://example.com/n) for the plan

**Why:** See [the report](https://example.com/r) for numbers.
"""


def test_links_show_as_their_text(tmp_path):
    a = _proj(tmp_path, "alpha", LINK_CL,
              "# Alpha — Backlog\n\n## Now\n- [ ] Read [the guide](https://example.com/g) first\n")
    v = views.project(a, TODAY)
    e = v["finished"][0]
    assert str(e["why"]) == "See the report for numbers."
    assert str(e["title"]) == "See the notes for the plan"
    assert str(v["up_next"][0]["items"][0]["headline"]) == "Read the guide first"
    row = views.dashboard([a], TODAY)["rows"][0]
    assert "](" not in str(row["last_title"]) and "](" not in str(row["next_up"])


def test_search_backlog_hit_strips_links_before_clamping(tmp_path):
    # Clamping first could cut a link in half, and a half link isn't
    # recognised as a link any more, so "[the…" showed as-is.
    head = " ".join(f"w{i}" for i in range(24)) + " [the report](https://example.com/r) needle"
    a = _proj(tmp_path, "alpha", None, f"# Alpha — Backlog\n\n## Now\n- [ ] {head}\n")
    [hit] = views.search([a], "needle", False, TODAY)[0]["hits"]
    assert "[" not in str(hit["text"]) and "](" not in str(hit["text"])
    assert str(hit["text"]).endswith("the…")


def test_clamped_headline_has_no_stray_backtick(tmp_path):
    words = " ".join(f"w{i}" for i in range(24))
    a = _proj(tmp_path, "alpha", None,
              f"# Alpha — Backlog\n\n## Now\n- [ ] {words} `make release` then more words\n")
    it = views.project(a, TODAY)["up_next"][0]["items"][0]
    assert "`" not in str(it["headline"])
    assert "<code>make release</code>" in it["note_html"]
