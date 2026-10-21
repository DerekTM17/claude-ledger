#!/usr/bin/env python3
"""Check every live ledger page for leaked markup, broken HTML and errors.

Usage: scripts/render_audit.py [base_url]   (default http://127.0.0.1:7777)
Fetches the dashboard, every project page linked from it, and a few searches.
Exits 1 if any page is not 200, has unbalanced tags, or shows raw markup
(comments, **bold**, ~~strike~~, [ ] boxes, ### headings, [text](links),
template syntax) in its visible text, or a template value that rendered as a
bare None/undefined: a text node that is exactly that word, an <input
value="None">, or a <textarea> holding just "None".

Text inside <code> and <pre> is left out of the markup scan: notes quote
`## Now`, `**kwargs` and `x=None` on purpose. A bare-word check (not a
`\bNone\b` search) keeps prose like "None of these" from counting.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
LEAKS = [re.compile(p) for p in (r"<!--", r"\*\*", r"~~", r"\[ \]", r"\[x\]", r"(?m)^\s*#{2,}\s", r"\]\(",
                                 r"\{\{", r"\{%")]
# What a template prints for a missing Python/JS value.
BARE_VALUES = {"None", "undefined"}
HIDDEN = ("script", "style", "title")
CODE = ("code", "pre")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []
        self.text: list[str] = []
        self.hidden = 0
        self.code = 0                   # depth inside <code>/<pre>
        self.bare: list[str] = []       # whole-value None/undefined leaks
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href", "").startswith("/p/"):
            self.links.append(a["href"])
        if tag == "input" and a.get("value") in BARE_VALUES:
            self.bare.append(f'<input name="{a.get("name", "")}" value="{a["value"]}">')
        if tag in VOID:
            return
        self.stack.append(tag)
        self._depth(tag, +1)

    def _depth(self, tag, step):
        if tag in HIDDEN:
            self.hidden += step
        if tag in CODE:
            self.code += step

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack:
                    popped = self.stack.pop()
                    self._depth(popped, -1)  # keep counts right past bad nesting
                    if popped == tag:
                        break
            return
        self.stack.pop()
        self._depth(tag, -1)

    def handle_data(self, data):
        # convert_charrefs=True hands over each text node whole, so a bare
        # "None" arrives as one piece. <textarea> content is a text node too.
        if self.hidden or self.code:
            return
        self.text.append(data)
        if data.strip() in BARE_VALUES:
            self.bare.append(f"text node {data.strip()!r} in <{self.stack[-1] if self.stack else '?'}>")


def leaks(page: Page) -> list[str]:
    """Leaked markup in the page's visible, non-code text, plus bare values."""
    problems = [f"bare value: {b}" for b in page.bare]
    visible = "\n".join(page.text)
    for rx in LEAKS:
        for m in rx.finditer(visible):
            ctx = visible[max(0, m.start() - 40): m.end() + 40].replace("\n", " ")
            problems.append(f"leak {rx.pattern!r}: …{ctx}…")
    return problems


def audit(base: str, path: str) -> tuple[list[str], list[str]]:
    try:
        with urllib.request.urlopen(base + path, timeout=20) as r:
            status, body = r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return [f"HTTP {e.code}"], []
    page = Page()
    page.feed(body)
    page.close()
    problems = [] if status == 200 else [f"HTTP {status}"]
    problems += page.errors
    if page.stack:
        problems.append(f"unclosed tags: {page.stack}")
    problems += leaks(page)
    return problems, page.links


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7777").rstrip("/")
    failed = 0
    problems, links = audit(base, "/")
    pages = ["/"] + sorted(set(links)) + ["/search", "/search?q=the", "/search?q=" + urllib.parse.quote('"Ledger"')]
    for path in pages:
        probs = problems if path == "/" else audit(base, path)[0]
        print(f"{'FAIL' if probs else 'ok  '} {path}")
        for p in probs[:15]:
            print(f"       {p}")
        failed += bool(probs)
    print(f"{len(pages) - failed}/{len(pages)} pages clean")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
