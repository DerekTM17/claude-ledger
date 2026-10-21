import html
import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    for slug in ("alpha", "beta"):
        p = proj_root / slug
        p.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
        (p / "docs").mkdir()
        (p / "docs" / "CHANGELOG.md").write_text(
            f"# {slug} — Changelog\n\n## 2026-05-18\n\n### Latest in {slug}\n"
        )
        (p / "docs" / "BACKLOG.md").write_text(
            f"# {slug} — Backlog\n\n## Now\n- [ ] {slug} now item\n\n## Soon\n\n## Someday\n"
        )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    from ledger.web import app
    return TestClient(app)


def test_dashboard_rows_have_plain_parts(web_client):
    r = web_client.get("/")
    assert r.status_code == 200
    assert 'id="project-list"' in r.text
    assert 'class="row"' in r.text and 'href="/p/alpha"' in r.text
    assert 'href="/p/beta"' in r.text
    assert "Finished" in r.text and "Next up" in r.text
    assert "alpha now item" in r.text
    assert "Latest in alpha" in r.text
    assert "to do now" in r.text
    assert "SYS" not in r.text and "grep //" not in r.text.lower()
    assert "<!--" not in r.text


def test_dashboard_rows_carry_sort_filter_data(web_client):
    r = web_client.get("/")
    for attr in ('data-slug="alpha"', "data-status=", "data-age=", "data-now=", "data-name=", "data-search="):
        assert attr in r.text


def test_dashboard_has_toolbar_and_stamp(web_client):
    r = web_client.get("/")
    assert 'id="board-toolbar"' in r.text and 'data-v="recent"' in r.text and 'data-v="quiet"' in r.text
    assert 'id="gen-stamp"' in r.text and "Updated" in r.text


def test_dashboard_has_status_key(web_client):
    from html.parser import HTMLParser

    r = web_client.get("/")
    assert 'class="key"' in r.text
    for label in (
        "Shipped today",
        "Active this week",
        "Active this month",
        "Quiet for over a month",
        "Nothing shipped yet",
    ):
        assert label in r.text

    class TreeCheck(HTMLParser):
        VOID = {"br", "img", "input", "hr", "meta", "link"}

        def __init__(self):
            super().__init__()
            self.stack = []
            self.key_ancestor_ids = None
            self.key_attrs = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get("class") == "key":
                self.key_ancestor_ids = [a.get("id") for _, a in self.stack]
                self.key_attrs = attrs
            if tag not in self.VOID:
                self.stack.append((tag, attrs))

        def handle_startendtag(self, tag, attrs):
            attrs = dict(attrs)
            if attrs.get("class") == "key":
                self.key_ancestor_ids = [a.get("id") for _, a in self.stack]
                self.key_attrs = attrs

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1][0] == tag:
                self.stack.pop()

    p = TreeCheck()
    p.feed(r.text)
    assert p.key_attrs is not None
    assert "board-toolbar" not in p.key_ancestor_ids
    assert "hidden" not in p.key_attrs


def test_key_never_dot_matches_row_hollow_treatment(web_client):
    # Rows draw "never" as a hollow ring, not a filled dot (no ship history to
    # show a solid color for). The key's "never" item must match, or the key
    # lies about what the row actually looks like.
    css = web_client.get("/static/style.css").text
    assert '.key li[data-status="never"]::before { background: transparent; border: 1.5px solid var(--st-never); }' in css
    # box-sizing: border-box (global `*` rule) keeps the bordered dot the same
    # 8px box as the filled ones, instead of growing past them.
    assert "* { box-sizing: border-box; }" in css


def test_stylesheet_keeps_hidden_elements_hidden(web_client):
    # The toolbar ships with `hidden` and JS reveals it; a class rule setting
    # `display` would override the attribute and show it with JS off.
    css = web_client.get("/static/style.css").text
    assert "[hidden] { display: none !important; }" in css


def test_dashboard_has_no_memory_text(web_client, monkeypatch):
    monkeypatch.delenv("LEDGER_NO_MEMORY", raising=False)
    r = web_client.get("/")
    assert "memory" not in r.text.lower()


def test_project_notes_render_markdown(web_client, monkeypatch, tmp_path):
    from ledger.memory import claude_slug
    # Memory descriptions carry **bold** and `code`; showing them as plain
    # text leaked the asterisks and backticks into the page.
    home = tmp_path / "home"
    mem = home / ".claude" / "projects" / claude_slug(home) / "memory"
    mem.mkdir(parents=True)
    (mem / "project_alpha.md").write_text(
        '---\ndescription: "Alpha tool. **Moved** to `main` <b>x</b>."\n---\n')
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LEDGER_NO_MEMORY", raising=False)
    r = web_client.get("/p/alpha")
    assert "<strong>Moved</strong>" in r.text and "<code>main</code>" in r.text
    assert "**" not in r.text and "<b>x</b>" not in r.text


def test_project_page_order_and_no_leaks(web_client):
    root = Path(os.environ["LEDGER_PROJECTS_ROOT"])
    (root / "alpha" / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\nIntro text that must not show.\n\n## Now\n"
        "- [ ] **[feat]** open now thing <!-- added 2026-09-15 -->\n  a `note` line\n"
        "- [x] done now thing <!-- added 2026-09-01 -->\n\n## Soon\n- [ ] soon thing\n\n## Someday\n"
    )
    r = web_client.get("/p/alpha")
    t = r.text
    assert r.status_code == 200
    assert t.index("Up next") < t.index("Recently finished") < t.index("For developers")
    assert "open now thing" in t and "Feature" in t
    assert "Latest in alpha" in t                 # Recently-finished entry title
    assert "Intro text that must not show" not in t
    assert "added 2026" not in t and "<!--" not in t and "**" not in t
    up_next = t[t.index("Up next"):t.index("Recently finished")]
    assert "done now thing" in t and "done now thing" not in up_next.split("Done:")[0]
    assert "<code>note</code>" in t


def test_project_page_developer_fold_has_commands_and_commits(web_client):
    r = web_client.get("/p/alpha")
    dev = r.text[r.text.index("For developers"):]
    assert "ledger ship alpha" in dev and "ledger idea alpha" in dev and "ledger done alpha" in dev
    assert "Recent commits" in dev
    # The fixture repo has no commits yet: say so without git's status names.
    assert "No commits to show." in dev and "no commits)" not in dev and "no_commits" not in dev


def test_project_view_unknown_404(web_client):
    r = web_client.get("/p/does-not-exist")
    assert r.status_code == 404


def test_search_returns_grouped_hits(web_client, tmp_path):
    proj_root = Path(os.environ.get("LEDGER_PROJECTS_ROOT"))
    (proj_root / "alpha" / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n- [ ] grok-the-thing today\n\n## Soon\n\n## Someday\n"
    )
    r = web_client.get("/search", params={"q": "grok-the-thing"})
    assert r.status_code == 200
    assert "alpha" in r.text
    assert "grok-the-thing" in r.text


def test_search_empty_q_shows_the_empty_state(web_client):
    # Used to return raw JSON {"detail": "empty query"}; an empty box is the
    # same as no query.
    for q in ("", "   ", '""'):
        r = web_client.get("/search", params={"q": q})
        assert r.status_code == 200, q
        assert "Type a word in the search box" in r.text
        assert "detail" not in r.text


def test_search_no_q_param_returns_empty_form(web_client):
    r = web_client.get("/search")
    assert r.status_code == 200


def test_project_view_missing_changelog_shows_hint(web_client):
    proj_root = Path(os.environ.get("LEDGER_PROJECTS_ROOT"))
    (proj_root / "alpha" / "docs" / "CHANGELOG.md").unlink()
    r = web_client.get("/p/alpha")
    assert r.status_code == 200
    assert "Nothing recorded yet." in r.text
    # Backlog panel should still render normally
    assert "alpha now item" in r.text


def test_project_view_disappears_when_git_removed(web_client):
    """Each request re-discovers projects; removing .git/ removes alpha
    from the dashboard. (recent_commits degradation itself is unit-tested in
    test_git.py — this test covers the discovery-side visible behavior.)"""
    import shutil
    proj_root = Path(os.environ["LEDGER_PROJECTS_ROOT"])
    shutil.rmtree(proj_root / "alpha" / ".git")
    r = web_client.get("/")
    assert "alpha" not in r.text
    assert "beta" in r.text  # beta unchanged


def test_favicon_is_inline(web_client):
    assert 'rel="icon" href="data:image/svg+xml' in web_client.get("/").text


def test_strikethrough_renders_in_notes():
    from ledger.markdown import render_text
    assert "<s>gone</s>" in render_text("~~gone~~")


def _git_seed(p: Path) -> None:
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "seed"],
        cwd=p, check=True,
    )


@pytest.fixture
def web_writes_client(tmp_path, monkeypatch):
    proj_root = tmp_path / "projects"
    p = proj_root / "alpha"
    p.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    (p / "docs").mkdir()
    (p / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n\n## Soon\n\n## Someday\n"
    )
    (p / "docs" / "CHANGELOG.md").write_text("# alpha — Changelog\n")
    _git_seed(p)
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    from ledger.web import app
    return TestClient(app), p


def test_post_backlog_writes_commits_and_redirects(web_writes_client):
    client, proj = web_writes_client
    r = client.post("/p/alpha/backlog",
                    data={"text": "the new thing", "horizon": "Soon"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/p/alpha"
    content = (proj / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    assert "the new thing" in content
    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=proj,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "docs(backlog)" in log


def test_post_backlog_rejects_empty_text(web_writes_client):
    client, _ = web_writes_client
    r = client.post("/p/alpha/backlog", data={"text": "", "horizon": "Soon"})
    assert r.status_code == 400


def test_post_backlog_403_when_writes_disabled(web_writes_client, monkeypatch):
    client, _ = web_writes_client
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "0")
    r = client.post("/p/alpha/backlog", data={"text": "x", "horizon": "Soon"})
    assert r.status_code == 403


def test_post_backlog_rejects_cross_origin(web_writes_client):
    client, _ = web_writes_client
    r = client.post(
        "/p/alpha/backlog",
        data={"text": "x", "horizon": "Soon"},
        headers={"Origin": "http://evil.example.com"},
    )
    assert r.status_code == 403


def test_post_backlog_rule_violation_rerenders_inline(web_client, monkeypatch):
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    r = web_client.post("/p/alpha/backlog", data={"text": "Paste it into config.js", "horizon": "Now", "tag": "", "note": "keep me"})
    assert r.status_code == 400
    assert 'class="form-errors"' in r.text and "config.js" in r.text
    assert "keep me" in r.text                      # typed text kept
    assert "<details class=\"fold dev\"" in r.text and " open" in r.text.split("For developers")[0][-200:]


def test_post_backlog_empty_optional_fields_dont_leak_none(web_client, monkeypatch):
    """FastAPI hands an unfilled optional field back as None; the re-render
    must show a blank field, not the literal word "None"."""
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    r = web_client.post("/p/alpha/backlog",
                        data={"text": "Paste it into config.js", "horizon": "Now",
                              "tag": "", "note": ""})
    assert r.status_code == 400
    assert 'value="None"' not in r.text
    assert ">None<" not in r.text


def test_post_backlog_note_is_saved(web_client, monkeypatch):
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    r = web_client.post("/p/alpha/backlog", data={"text": "Link the feedback form", "horizon": "Now",
                                                  "note": "See the config file."}, follow_redirects=False)
    assert r.status_code == 303
    text = (Path(os.environ["LEDGER_PROJECTS_ROOT"]) / "alpha" / "docs" / "BACKLOG.md").read_text()
    assert "  See the config file.\n" in text


def test_post_changelog_writes_commits_and_redirects(web_writes_client):
    client, proj = web_writes_client
    r = client.post("/p/alpha/changelog",
                    data={"title": "Did the thing", "why": "needed it"},
                    follow_redirects=False)
    assert r.status_code == 303
    content = (proj / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Did the thing" in content
    assert "needed it" in content


def test_post_changelog_rejects_empty_title(web_writes_client):
    client, _ = web_writes_client
    r = client.post("/p/alpha/changelog", data={"title": "", "why": ""})
    assert r.status_code == 400


def test_project_page_renders_forms_when_writes_enabled(web_writes_client):
    client, _ = web_writes_client
    r = client.get("/p/alpha")
    assert 'id="form-backlog"' in r.text
    assert 'id="form-changelog"' in r.text


def test_project_page_hides_forms_when_writes_disabled(web_writes_client, monkeypatch):
    client, _ = web_writes_client
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "0")
    r = client.get("/p/alpha")
    assert 'id="form-backlog"' not in r.text
    assert 'id="form-changelog"' not in r.text


def test_post_backlog_rejects_substring_origin_attack(web_writes_client):
    """Regression: substring check would let 'evil-localhost:7777.attacker.com' pass."""
    client, _ = web_writes_client
    r = client.post(
        "/p/alpha/backlog",
        data={"text": "x", "horizon": "Soon"},
        headers={"Origin": "http://evil-localhost:7777.attacker.com"},
    )
    assert r.status_code == 403


# ─── dashboard sort / filter / freshness (2026-07) ────────────────────

@pytest.fixture
def web_client_dated(tmp_path, monkeypatch):
    """Two projects shipped on different dates so recency ordering is testable.

    older=alpha (2026-05-10), newer=beta (2026-05-20).
    """
    proj_root = tmp_path / "projects"
    dates = {"alpha": "2026-05-10", "beta": "2026-05-20"}
    for slug, d in dates.items():
        p = proj_root / slug
        p.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
        (p / "docs").mkdir()
        (p / "docs" / "CHANGELOG.md").write_text(
            f"# {slug} — Changelog\n\n## {d}\n\n### Latest in {slug}\n"
        )
        (p / "docs" / "BACKLOG.md").write_text(
            f"# {slug} — Backlog\n\n## Now\n- [ ] {slug} now one\n- [ ] {slug} now two\n\n## Soon\n\n## Someday\n"
        )
    monkeypatch.setenv("LEDGER_PROJECTS_ROOT", str(proj_root))
    monkeypatch.setenv("LEDGER_NO_MEMORY", "1")
    from ledger.web import app
    return TestClient(app)


def test_dashboard_default_sort_is_recency(web_client_dated):
    """Most-recently-shipped project renders before older ones by default."""
    r = web_client_dated.get("/")
    assert r.status_code == 200
    # beta (2026-05-20) is newer than alpha (2026-05-10) -> beta first
    assert r.text.index('data-slug="beta"') < r.text.index('data-slug="alpha"')
    assert 'data-now="2"' in r.text  # 2 Now items in the fixture


def test_dashboard_shows_freshness_stamp(web_client_dated):
    """A 'data as of' element is present so an always-open board shows its age."""
    r = web_client_dated.get("/")
    assert 'id="gen-stamp"' in r.text
    assert 'data-generated=' in r.text       # ISO timestamp for the JS age ticker


def test_dashboard_has_toolbar_controls(web_client_dated):
    """Sort control and filter chips exist, with machine-readable values."""
    r = web_client_dated.get("/")
    assert 'id="board-toolbar"' in r.text
    assert 'data-v="all"' in r.text and 'data-v="active"' in r.text  # filter chips


def test_search_quoted_query_is_case_sensitive(web_client):
    proj_root = Path(os.environ.get("LEDGER_PROJECTS_ROOT"))
    (proj_root / "alpha" / "docs" / "BACKLOG.md").write_text(
        "# alpha — Backlog\n\n## Now\n- [ ] Widget-Upper\n- [ ] widget-lower\n\n## Soon\n\n## Someday\n"
    )
    # A match is wrapped in <mark>, so check the surviving fragments rather
    # than the whole word.
    r = web_client.get("/search", params={"q": '"Widget"'})
    assert r.status_code == 200
    assert "<mark>Widget</mark>-Upper" in r.text
    assert "-lower" not in r.text
    # Unquoted stays case-insensitive.
    r = web_client.get("/search", params={"q": "Widget"})
    assert "<mark>Widget</mark>-Upper" in r.text and "<mark>widget</mark>-lower" in r.text


def test_search_page_groups_and_highlights(web_client):
    r = web_client.get("/search", params={"q": "now item"})
    assert r.status_code == 200
    assert "<mark>now item</mark>" in r.text
    assert 'href="/p/alpha"' in r.text


def test_post_changelog_rule_violation_is_400_and_writes_nothing(web_client, monkeypatch):
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    path = Path(os.environ["LEDGER_PROJECTS_ROOT"]) / "alpha" / "docs" / "CHANGELOG.md"
    before = path.read_text()
    r = web_client.post("/p/alpha/changelog", data={"title": "Merged PR #92", "why": ""})
    assert r.status_code == 400
    assert "PR #92" in r.text
    assert 'value="None"' not in r.text and ">None<" not in r.text
    assert path.read_text() == before


def test_header_search_box_is_required(web_client):
    r = web_client.get("/")
    box = re.search(r'<input id="q"[^>]*>', r.text).group(0)
    assert " required" in box


def test_each_search_hit_links_to_its_project(web_client):
    r = web_client.get("/search", params={"q": "alpha"})
    hits = re.findall(r'<li class="item">.*?</li>', r.text, re.S)
    assert hits
    for h in hits:
        assert 'href="/p/alpha"' in h


def test_link_in_why_shows_as_its_text(web_client):
    path = Path(os.environ["LEDGER_PROJECTS_ROOT"]) / "alpha" / "docs" / "CHANGELOG.md"
    path.write_text("# alpha — Changelog\n\n## 2026-05-18\n\n### Latest in alpha\n\n"
                    "**Why:** See [the report](https://example.com/r) for numbers.\n")
    r = web_client.get("/p/alpha")
    assert "See the report for numbers." in r.text
    assert "](" not in r.text


def test_post_backlog_bad_tag_rerenders_inline(web_client, monkeypatch):
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")
    path = Path(os.environ["LEDGER_PROJECTS_ROOT"]) / "alpha" / "docs" / "BACKLOG.md"
    before = path.read_text()
    r = web_client.post("/p/alpha/backlog", data={"text": "Fix the footer", "horizon": "Now",
                                                  "tag": "two words", "note": ""})
    assert r.status_code == 400
    assert 'class="form-errors"' in r.text and "Tag:" in r.text
    assert 'value="two words"' in r.text and 'value="Fix the footer"' in r.text
    assert path.read_text() == before


def test_tag_input_has_maxlength(web_writes_client):
    client, _ = web_writes_client
    box = re.search(r'<input id="f-tag"[^>]*>', client.get("/p/alpha").text).group(0)
    assert 'maxlength="20"' in box


def test_post_changelog_403_when_writes_disabled(web_writes_client, monkeypatch):
    client, proj = web_writes_client
    before = (proj / "docs" / "CHANGELOG.md").read_text()
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "0")
    r = client.post("/p/alpha/changelog", data={"title": "Did the thing", "why": "It helps."})
    assert r.status_code == 403
    assert (proj / "docs" / "CHANGELOG.md").read_text() == before


def test_post_changelog_rejects_cross_origin(web_writes_client):
    client, proj = web_writes_client
    before = (proj / "docs" / "CHANGELOG.md").read_text()
    for origin in ("http://evil.example.com", "http://evil-localhost:7777.attacker.com"):
        r = client.post("/p/alpha/changelog", data={"title": "Did the thing", "why": "It helps."},
                        headers={"Origin": origin})
        assert r.status_code == 403, origin
    assert (proj / "docs" / "CHANGELOG.md").read_text() == before


# ─── hostile file content never reaches the page unescaped ─────────────

EVIL_CL = """# <script>alert('h1')</script> — Changelog

## 2026-05-18

### Title "><img src=x onerror=alert('title')>

**Why:** Why <script>alert('why')</script> and [click](javascript:alert('why')).

Extra <script>alert('more')</script> [x](javascript:alert('more')) "><img src=x onerror=alert('more')>
"""
EVIL_BL = """# <script>alert('h1b')</script> — Backlog

## Now

### Sub <script>alert('h3')</script> "><img src=x onerror=alert('h3')>
- [ ] **[<script>alert('tag')</script>]** Head "><img src=x onerror=alert('head')> [c](javascript:alert('head')) <!-- added 2026-05-15 -->
  Note <script>alert('note')</script> [n](javascript:alert('note')) "><img src=x onerror=alert('note')>

## Soon

## Someday
"""
EVIL_DONE = """# Evil — Done

## 2026-05-01

- [x] Done <script>alert('done')</script> "><img src=x onerror=alert('done')> <!-- from Now -->
  Note [d](javascript:alert('done'))
"""


def _assert_inert(html: str) -> None:
    assert "<script>alert" not in html
    assert "<img" not in html
    assert not re.search(r"""href\s*=\s*["']?\s*javascript:""", html, re.I)


def test_hostile_file_content_is_escaped_everywhere(web_client, monkeypatch):
    root = Path(os.environ["LEDGER_PROJECTS_ROOT"])
    p = root / "evil"
    p.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)
    (p / "docs").mkdir()
    (p / "docs" / "CHANGELOG.md").write_text(EVIL_CL)
    (p / "docs" / "BACKLOG.md").write_text(EVIL_BL)
    (p / "docs" / "BACKLOG-DONE.md").write_text(EVIL_DONE)
    monkeypatch.setenv("LEDGER_ALLOW_WRITES", "1")

    pages = {
        "dashboard": web_client.get("/"),
        "project": web_client.get("/p/evil"),
        "search": web_client.get("/search", params={"q": "alert"}),
        "hostile query": web_client.get("/search", params={"q": "<script>alert(1)</script>"}),
        "backlog form": web_client.post("/p/evil/backlog", data={
            "text": "<script>alert('f')</script> in config.js", "horizon": "Now",
            "tag": "\"><img src=x onerror=alert('ftag')>",
            "note": "</textarea><script>alert('fnote')</script>"}),
        "changelog form": web_client.post("/p/evil/changelog", data={
            "title": "\"><img src=x onerror=alert('ft')> in config.js",
            "why": "</textarea><script>alert('fwhy')</script>"}),
    }
    # The hostile parts really are on the page, as text, not silently dropped.
    shown = html.unescape(pages["project"].text)
    for part in ("h1", "title", "why", "more", "h3", "tag", "head", "note", "done"):
        assert f"alert('{part}')" in shown, part
    assert "evil" in pages["search"].text
    for name, r in pages.items():
        assert r.status_code in (200, 400), name
        _assert_inert(r.text)
    assert pages["backlog form"].status_code == 400 and pages["changelog form"].status_code == 400


def test_dashboard_static_links_carry_a_version_tag(web_client):
    r = web_client.get("/")
    assert re.search(r'href="[^"]*/static/style\.css\?v=[0-9a-f]{8}"', r.text)
    assert re.search(r'src="[^"]*/static/dashboard\.js\?v=[0-9a-f]{8}"', r.text)


def test_static_version_changes_with_content_and_is_stable_otherwise(tmp_path):
    from ledger.web import _static_version

    f = tmp_path / "style.css"
    f.write_text("body { color: red; }")
    first = _static_version(f)
    again = _static_version(f)
    assert first == again  # unchanged file -> same tag, not rehashed

    f.write_text("body { color: blue; }")
    # Force a distinct mtime: some filesystems have coarse mtime resolution,
    # so a same-tick rewrite wouldn't otherwise be detected as changed.
    new_mtime = f.stat().st_mtime + 1
    os.utime(f, (new_mtime, new_mtime))
    changed = _static_version(f)
    assert changed != first


def test_static_version_of_missing_file_yields_usable_url():
    from ledger.web import _static_version, static_url

    missing = Path("/nonexistent/does-not-exist.css")
    assert _static_version(missing) == ""

    class _FakeRequest:
        def url_for(self, name, **path_params):
            return f"http://testserver/{name}/{path_params.get('path', '')}"

    url = static_url(_FakeRequest(), "does-not-exist.css")
    assert url == "http://testserver/static/does-not-exist.css"
    assert "?v=" not in url
