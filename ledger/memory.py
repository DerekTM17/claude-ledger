"""Resolve a project slug to its auto-memory file + extract description."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

def claude_slug(path: Path) -> str:
    """Claude Code's folder name for a launch directory: every character that
    isn't a letter or digit becomes `-` (`/home/me` -> `-home-me`)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _default_memory_root() -> Path:
    """Resolved at call time, not import time, so a test's `HOME` override
    (e.g. monkeypatched in conftest) actually takes effect.

    Assumes Claude Code is launched from the home directory; set
    `LEDGER_MEMORY_ROOT` when it is launched from somewhere else."""
    override = os.environ.get("LEDGER_MEMORY_ROOT")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    return home / ".claude" / "projects" / claude_slug(home) / "memory"


# Kept for backward compatibility with anything importing the constant
# directly; frozen at import time like before. `memory_path_for` itself no
# longer reads this — it calls `_default_memory_root()` fresh instead.
DEFAULT_MEMORY_ROOT = _default_memory_root()
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
DESCRIPTION_LINE_RE = re.compile(r'^description:\s*"?(.+?)"?\s*$', re.MULTILINE)
# Body lines that are just decoration (e.g. "# ════════════════════════════")
# — used when falling back from frontmatter to the body's first real line.
# Range ─-▟ covers all Unicode box-drawing + block characters.
DECORATION_RE = re.compile(r'^[#\-=*_\s─-▟]+$')


def memory_path_for(slug: str, memory_root: Path | None = None,
                    override: str | None = None) -> Path:
    """Return the expected memory file path for a project slug."""
    root = memory_root or _default_memory_root()
    filename = override or f"project_{slug.replace('-', '_')}.md"
    return root / filename


def _description_from_frontmatter(block: str) -> str | None:
    """Pull `description:` out of a frontmatter block, tolerating YAML parse errors.

    Memory files occasionally contain unquoted `description:` values with
    mid-value colons (e.g. "tests): state-aggregate"), which break strict YAML.
    Fall back to a line-regex when that happens.
    """
    try:
        front = yaml.safe_load(block) or {}
        if isinstance(front, dict):
            desc = front.get("description")
            if desc:
                return str(desc).strip()
    except yaml.YAMLError:
        pass
    m = DESCRIPTION_LINE_RE.search(block)
    if m:
        return m.group(1).strip()
    return None


def read_description(path: Path) -> str | None:
    """Return the `description:` from frontmatter, or first non-decoration body line, or None."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if m:
        desc = _description_from_frontmatter(m.group(1))
        if desc:
            return desc
        body = text[m.end():]
    else:
        body = text
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not DECORATION_RE.match(stripped):
            return stripped
    return None
