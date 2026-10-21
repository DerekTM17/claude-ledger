"""Defensive git commit helper for ledger writes. Fail-soft: never raises."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_AUTHOR_NAME = "ledger"
DEFAULT_AUTHOR_EMAIL = "ledger@localhost"


@dataclass(frozen=True)
class CommitResult:
    committed: bool
    sha: str | None
    skipped_reason: str | None


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=10,
    )


def _unsafe_repo_state(repo: Path) -> str | None:
    """Return a reason string if commit is unsafe, else None."""
    if not (repo / ".git").exists():
        return "not a git repo"
    git_dir = repo / ".git"
    head = _run(["git", "symbolic-ref", "-q", "HEAD"], repo)
    if head.returncode != 0:
        return "detached HEAD"
    if (git_dir / "MERGE_HEAD").exists():
        return "mid-merge"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "mid-rebase"
    return None


def _is_gitignored(repo: Path, specs: list[str]) -> bool:
    r = _run(["git", "check-ignore", "-q", "--", *specs], repo)
    return r.returncode == 0  # exit 0 means ignored


def _has_identity(repo: Path) -> bool:
    # Check if both user.name and user.email are configured
    # (at local, global, or system level). If either is missing, use fallback.
    name = _run(["git", "config", "user.name"], repo).stdout.strip()
    email = _run(["git", "config", "user.email"], repo).stdout.strip()
    return bool(name) and bool(email)


def commit_file(repo: Path, pathspec: str | list[str], message: str,
                max_lock_retries: int = 1) -> CommitResult:
    """Commit one or more pathspecs in `repo`. Never raises.

    Skips cleanly on detached HEAD / mid-merge / mid-rebase / gitignored file.
    Uses --no-verify (dodges project pre-commit hooks). Commits ONLY the given
    pathspec(s) — never sweeps other staged/unstaged changes. Retries on
    index.lock and detects nothing-to-commit as a no-op (not an error).
    """
    specs = [pathspec] if isinstance(pathspec, str) else list(pathspec)
    try:
        reason = _unsafe_repo_state(repo)
        if reason:
            return CommitResult(False, None, reason)
        if _is_gitignored(repo, specs):
            return CommitResult(False, None, "gitignored")

        # Stage the files (needed for never-tracked paths like a fresh SESSIONS.md)
        add = _run(["git", "add", *specs], repo)
        if add.returncode != 0:
            return CommitResult(False, None, f"git add failed: {add.stderr.strip()[:200]}")

        cmd = ["git"]
        if not _has_identity(repo):
            cmd += ["-c", f"user.name={DEFAULT_AUTHOR_NAME}",
                    "-c", f"user.email={DEFAULT_AUTHOR_EMAIL}"]
        cmd += ["commit", "--no-verify", "-m", message, "--", *specs]

        for attempt in range(max_lock_retries + 1):
            r = _run(cmd, repo)
            if r.returncode == 0:
                sha = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
                return CommitResult(True, sha, None)
            stdout_low = r.stdout.lower()
            stderr_low = r.stderr.lower()
            if "nothing to commit" in stdout_low or "no changes added" in stdout_low:
                sha = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
                return CommitResult(False, sha, "nothing to commit")
            if "index.lock" in stderr_low and attempt < max_lock_retries:
                time.sleep(0.1)
                continue
            return CommitResult(False, None, f"git error: {r.stderr.strip()[:200]}")
        return CommitResult(False, None, "exhausted retries")
    except Exception as e:  # noqa: BLE001
        return CommitResult(False, None, f"unexpected: {type(e).__name__}: {e}")
