"""Wrap `git log` for the 'Recent commits' panel. Degrades gracefully."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class Commit:
    sha: str
    date: str
    subject: str


@dataclass
class GitResult:
    status: Literal["ok", "not_a_repo", "no_commits", "git_missing", "error"]
    commits: list[Commit] = field(default_factory=list)
    message: str = ""


def recent_commits(repo: Path, limit: int = 10) -> GitResult:
    if shutil.which("git") is None:
        return GitResult(status="git_missing", message="git binary not on PATH")
    if not (repo / ".git").exists():
        return GitResult(status="not_a_repo")
    fmt = "%h\x1f%ad\x1f%s"
    try:
        proc = subprocess.run(
            ["git", "log", f"-{limit}", "--date=short", f"--pretty=format:{fmt}"],
            cwd=repo, capture_output=True, text=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        return GitResult(status="error", message="git log timed out")
    if proc.returncode != 0:
        # An empty repo prints to stderr "fatal: your current branch ... does not have any commits yet"
        stderr = proc.stderr.lower()
        if "does not have any commits" in stderr or "bad default revision" in stderr:
            return GitResult(status="no_commits")
        return GitResult(status="error", message=proc.stderr.strip())
    commits = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        sha, date, subject = line.split("\x1f", 2)
        commits.append(Commit(sha=sha, date=date, subject=subject))
    return GitResult(status="ok", commits=commits)
