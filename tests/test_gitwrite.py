import os
import subprocess
from pathlib import Path

import pytest

from ledger.gitwrite import commit_file, CommitResult


def test_commit_file_happy_path(git_repo: Path):
    (git_repo / "docs").mkdir()
    target = git_repo / "docs" / "NOTES.md"
    target.write_text("hello world\n")

    result = commit_file(git_repo, "docs/NOTES.md", "docs: add notes")

    assert result.committed is True
    assert result.sha is not None and len(result.sha) == 40
    assert result.skipped_reason is None
    # File is in HEAD
    out = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD", "docs/NOTES.md"],
        cwd=git_repo, capture_output=True, text=True, check=True,
    )
    assert "docs/NOTES.md" in out.stdout


def test_commit_file_does_not_sweep_unrelated_changes(git_repo: Path):
    # Two dirty files; commit only one — the other stays dirty.
    (git_repo / "a.txt").write_text("A\n")
    (git_repo / "b.txt").write_text("B\n")
    subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "seed"],
        cwd=git_repo, check=True,
    )
    (git_repo / "a.txt").write_text("A modified\n")
    (git_repo / "b.txt").write_text("B modified\n")

    result = commit_file(git_repo, "a.txt", "docs: only a")
    assert result.committed is True

    # b.txt is still dirty
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "b.txt" in status
    assert "a.txt" not in status  # a was committed


def test_commit_file_skips_on_detached_head(git_repo: Path):
    # Detach
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=git_repo,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "--detach", sha, "-q"],
                   cwd=git_repo, check=True)
    (git_repo / "x.txt").write_text("x\n")

    result = commit_file(git_repo, "x.txt", "msg")
    assert result.committed is False
    assert result.skipped_reason == "detached HEAD"


def test_commit_file_skips_mid_merge(git_repo: Path):
    # Simulate mid-merge by touching .git/MERGE_HEAD
    (git_repo / ".git" / "MERGE_HEAD").write_text("dummy\n")
    (git_repo / "x.txt").write_text("x\n")

    result = commit_file(git_repo, "x.txt", "msg")
    assert result.committed is False
    assert result.skipped_reason == "mid-merge"


def test_commit_file_skips_gitignored(git_repo: Path):
    (git_repo / ".gitignore").write_text("ignored.txt\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add gitignore"],
                   cwd=git_repo, check=True)
    (git_repo / "ignored.txt").write_text("nope\n")

    result = commit_file(git_repo, "ignored.txt", "msg")
    assert result.committed is False
    assert result.skipped_reason == "gitignored"


def test_commit_file_uses_author_fallback_when_identity_missing(tmp_path: Path, monkeypatch):
    # A git_repo without configured identity (override HOME to prevent global config)
    repo = tmp_path / "noid"
    repo.mkdir()

    # Set HOME to a temporary directory to isolate from global ~/.gitconfig
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Also set GIT_CONFIG_GLOBAL to /dev/null as a backup isolation method
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")

    env = os.environ.copy()

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "-c", "user.email=seed@t", "-c", "user.name=seed",
         "commit", "-q", "-m", "seed"],
        cwd=repo, check=True, env=env,
    )

    (repo / "n.txt").write_text("n\n")
    result = commit_file(repo, "n.txt", "no-id commit")
    assert result.committed is True

    author = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert author == "ledger <ledger@localhost>"


def test_commit_file_no_op_when_nothing_to_commit(git_repo: Path):
    # README.md is already committed and unchanged.
    result = commit_file(git_repo, "README.md", "no change")
    assert result.committed is False
    assert result.skipped_reason == "nothing to commit"
    assert result.sha is not None  # HEAD sha (existing)


def test_commit_file_accepts_list_of_pathspecs(git_repo: Path):
    (git_repo / "docs").mkdir()
    (git_repo / "docs" / "a.md").write_text("a\n")
    (git_repo / "docs" / "b.md").write_text("b\n")
    (git_repo / "c.txt").write_text("untouched\n")  # dirty, but not passed in

    result = commit_file(git_repo, ["docs/a.md", "docs/b.md"], "docs: add a and b")

    assert result.committed is True
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=git_repo, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert set(show) == {"docs/a.md", "docs/b.md"}
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=git_repo,
        capture_output=True, text=True, check=True,
    ).stdout
    assert "c.txt" in status


def test_commit_file_retries_on_index_lock(git_repo: Path, monkeypatch):
    """Simulate one transient index.lock by removing it after the first commit call."""
    lock = git_repo / ".git" / "index.lock"
    calls = {"n": 0}

    real_run = subprocess.run

    def flaky_run(args, **kw):
        # On the first `git commit ...` invocation, create the lock so the
        # first commit fails, then remove it so the retry succeeds.
        if calls["n"] == 0 and len(args) >= 2 and args[0] == "git" and "commit" in args:
            calls["n"] += 1
            lock.write_text("")
            # Let the real git see the lock and fail
            res = real_run(args, **kw)
            # Clear it so the retry succeeds
            if lock.exists():
                lock.unlink()
            return res
        return real_run(args, **kw)

    monkeypatch.setattr(subprocess, "run", flaky_run)
    (git_repo / "x.txt").write_text("x\n")
    result = commit_file(git_repo, "x.txt", "retry case", max_lock_retries=1)
    assert result.committed is True
