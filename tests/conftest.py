"""Shared pytest fixtures."""
import shutil
import subprocess
from pathlib import Path

import pytest

from ledger.models import Project

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch):
    """Never let a test read or write real ledger state or config.

    `LEDGER_STATE_PATH` isolates state.json directly. `HOME` isolates
    `default_config_path()` (~/.config/ledger/projects.yaml), which has no
    env override of its own — without this, a developer's real config
    (e.g. an `include:` entry for an unrelated project) leaks extra rows
    into `status` output and can make width-sensitive assertions flaky.
    """
    monkeypatch.setenv("LEDGER_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("LEDGER_MEMORY_ROOT", raising=False)


@pytest.fixture
def tmp_project(tmp_path: Path) -> Project:
    """Copy sample_project into tmp_path and git-init it. Returns a Project."""
    dest = tmp_path / "sample-project"
    shutil.copytree(FIXTURE_DIR, dest)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test", "-c", "user.name=test",
         "commit", "-q", "-m", "init"],
        cwd=dest, check=True,
    )
    return Project(slug="sample-project", path=dest)


@pytest.fixture
def empty_project(tmp_path: Path) -> Project:
    """A project with .git/ but no docs/ — for lazy-creation tests."""
    dest = tmp_path / "empty-project"
    dest.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    return Project(slug="empty-project", path=dest)


def assert_unchanged_outside(before: str, after: str, insert_start: int, insert_len: int):
    """All lines outside the inserted region must be byte-equal.

    `insert_start` is 0-indexed line offset where the new content begins.
    `insert_len` is the number of lines inserted.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    assert before_lines[:insert_start] == after_lines[:insert_start], \
        "content before insertion was modified"
    assert before_lines[insert_start:] == after_lines[insert_start + insert_len:], \
        "content after insertion was modified"


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A minimal git repo with one tracked file and configured identity.

    For low-level gitwrite tests that don't need ledger docs/.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo
