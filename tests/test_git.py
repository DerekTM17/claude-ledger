import subprocess
from pathlib import Path

from ledger.git import recent_commits, GitResult


def _run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   capture_output=True)


def test_recent_commits_returns_commits_in_real_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _run("git", "init", "-q", "-b", "main", cwd=repo)
    _run("git", "config", "user.email", "t@t", cwd=repo)
    _run("git", "config", "user.name", "t", cwd=repo)
    (repo / "a.txt").write_text("a")
    _run("git", "add", "a.txt", cwd=repo)
    _run("git", "commit", "-q", "-m", "first commit", cwd=repo)
    (repo / "b.txt").write_text("b")
    _run("git", "add", "b.txt", cwd=repo)
    _run("git", "commit", "-q", "-m", "second commit", cwd=repo)

    result = recent_commits(repo, limit=10)
    assert result.status == "ok"
    assert len(result.commits) == 2
    # Newest first
    assert result.commits[0].subject == "second commit"
    assert result.commits[1].subject == "first commit"
    assert len(result.commits[0].sha) == 7  # short SHA


def test_recent_commits_not_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = recent_commits(plain)
    assert result.status == "not_a_repo"
    assert result.commits == []


def test_recent_commits_repo_with_zero_commits(tmp_path):
    repo = tmp_path / "r2"
    repo.mkdir()
    _run("git", "init", "-q", "-b", "main", cwd=repo)
    result = recent_commits(repo)
    assert result.status == "no_commits"
    assert result.commits == []
