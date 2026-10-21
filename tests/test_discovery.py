import subprocess
from pathlib import Path

from ledger.config import LedgerConfig
from ledger.discovery import discover_projects


def _git_init(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=p, check=True)


def test_auto_scan_finds_git_subdirs(tmp_path):
    root = tmp_path / "projects"
    _git_init(root / "alpha")
    _git_init(root / "beta")
    (root / "not-a-repo").mkdir()
    projects = discover_projects(projects_root=root, config=LedgerConfig())
    slugs = {p.slug for p in projects}
    assert slugs == {"alpha", "beta"}


def test_exclude_removes_named_project(tmp_path):
    root = tmp_path / "projects"
    _git_init(root / "alpha")
    _git_init(root / "beta")
    cfg = LedgerConfig(exclude=["beta"])
    projects = discover_projects(projects_root=root, config=cfg)
    assert {p.slug for p in projects} == {"alpha"}


def test_include_adds_external_path(tmp_path):
    root = tmp_path / "projects"
    _git_init(root / "alpha")
    external = tmp_path / "elsewhere" / "gamma"
    _git_init(external)
    cfg = LedgerConfig(include=[{"path": str(external)}])
    projects = discover_projects(projects_root=root, config=cfg)
    assert {p.slug for p in projects} == {"alpha", "gamma"}


def test_include_slug_override(tmp_path):
    external = tmp_path / "elsewhere" / "long-name-thing"
    _git_init(external)
    cfg = LedgerConfig(include=[{"path": str(external), "slug": "lnt"}])
    projects = discover_projects(projects_root=tmp_path / "absent", config=cfg)
    assert [p.slug for p in projects] == ["lnt"]


def test_projects_returned_sorted_by_slug(tmp_path):
    root = tmp_path / "projects"
    _git_init(root / "zebra")
    _git_init(root / "alpha")
    _git_init(root / "mango")
    projects = discover_projects(projects_root=root, config=LedgerConfig())
    assert [p.slug for p in projects] == ["alpha", "mango", "zebra"]
