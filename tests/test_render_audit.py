"""The render audit flags template leaks but not the same words in real content."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "render_audit.py"
_spec = importlib.util.spec_from_file_location("render_audit", _PATH)
render_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_audit)


def _leaks(html: str) -> list[str]:
    page = render_audit.Page()
    page.feed(html)
    page.close()
    return render_audit.leaks(page)


def test_prose_and_code_are_not_leaks():
    html = ("<main><p>None of these ship today.</p>"
            "<p>Put it under <code>## Now</code> and set <code>None</code>.</p>"
            "<pre>**bold** in a code block\n### heading</pre></main>")
    assert _leaks(html) == []


def test_whole_none_values_are_leaks():
    assert _leaks("<main><span>None</span></main>")
    assert _leaks("<main><span> undefined </span></main>")
    assert _leaks('<form><input name="tag" value="None"></form>')
    assert _leaks("<form><textarea>None</textarea></form>")


def test_markup_outside_code_is_still_a_leak():
    assert _leaks("<main><p>**bold** left raw</p></main>")
    assert _leaks("<main><p>kept <code>`x`</code> but ~~struck~~</p></main>")
