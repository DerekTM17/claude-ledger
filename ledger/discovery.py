"""Enumerate projects: auto-scan ~/projects/ + apply yaml overrides."""
from __future__ import annotations

from pathlib import Path

from ledger.config import LedgerConfig
from ledger.models import Project


def default_projects_root() -> Path:
    return Path.home() / "projects"


def _is_git_repo(p: Path, include_worktrees: bool = False) -> bool:
    # A worktree's `.git` is a file pointing back at the main repo. It holds
    # a copy of that project's docs, so listing it would count the project
    # twice.
    git = p / ".git"
    return p.is_dir() and (git.exists() if include_worktrees else git.is_dir())


def discover_projects(projects_root: Path | None = None,
                      config: LedgerConfig | None = None,
                      include_worktrees: bool = False) -> list[Project]:
    """Return projects in slug-sorted order.

    Auto-scans `projects_root` for immediate subdirs with `.git/`. Applies
    `config.exclude` (by slug) and `config.include` (external paths).
    Worktrees are left out unless `include_worktrees` is set.
    """
    root = projects_root or default_projects_root()
    cfg = config or LedgerConfig()

    found: dict[str, Project] = {}

    if root.exists():
        for child in root.iterdir():
            if _is_git_repo(child, include_worktrees):
                slug = child.name
                if slug not in cfg.exclude:
                    found[slug] = Project(slug=slug, path=child.resolve())

    for entry in cfg.include:
        path_str = entry.get("path")
        if not path_str:
            continue
        ext_path = Path(path_str).expanduser().resolve()
        slug = entry.get("slug") or ext_path.name
        if slug in cfg.exclude:
            continue
        found[slug] = Project(slug=slug, path=ext_path)

    return sorted(found.values(), key=lambda p: p.slug)
