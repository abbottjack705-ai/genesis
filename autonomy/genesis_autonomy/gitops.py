"""Explicit wrappers over the git CLI. Every failure raises WorkflowError (fail closed)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .state import WorkflowError


# core.longpaths: the evidence tree holds paths deeper than MAX_PATH; without it a detached validation
# checkout under a deep worktree root fails with "Filename too long" (reproduced in the end-to-end run).
GIT_BASE = ["-c", "core.quotepath=off", "-c", "core.longpaths=true"]


def git(cwd, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *GIT_BASE, *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise WorkflowError("GIT_FAILED", f"git {' '.join(args)} exited {proc.returncode}: "
                                          f"{proc.stderr.strip()[:500]}")
    return proc.stdout


def same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def toplevel(cwd) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel").strip())


def common_dir(cwd) -> Path:
    raw = Path(git(cwd, "rev-parse", "--git-common-dir").strip())
    return raw if raw.is_absolute() else (Path(cwd) / raw).resolve()


def head(cwd) -> str:
    return git(cwd, "rev-parse", "HEAD").strip()


def branch(cwd) -> str:
    return git(cwd, "rev-parse", "--abbrev-ref", "HEAD").strip()


def is_clean(cwd) -> bool:
    return git(cwd, "status", "--porcelain", "--untracked-files=all").strip() == ""


def is_ancestor(cwd, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant],
                          cwd=str(cwd), capture_output=True)
    return proc.returncode == 0


def changed_paths(cwd, base: str, tip: str) -> list[str]:
    # --no-renames: a rename reports both the old and the new path, so moving a frozen file out of
    # src/ or tests/ cannot hide behind its new name (found by the end-to-end skeptic review).
    return [line for line in git(cwd, "diff", "--name-only", "--no-renames", base, tip).splitlines() if line]


def diff_stat(cwd, base: str, tip: str) -> str:
    return git(cwd, "diff", "--stat", base, tip)


def diff_text(cwd, base: str, tip: str) -> str:
    return git(cwd, "diff", "--no-color", base, tip)


def add_worktree_detached(repo, path: Path, sha: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(path), sha)


def remove_worktree(repo, path: Path) -> None:
    if path.exists():
        git(repo, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git(repo, "worktree", "prune", check=False)


def commit_paths(cwd, paths: list[str], message: str) -> str:
    """Stage exactly ``paths`` and commit them. The caller guarantees the rest of the tree is clean."""
    git(cwd, "add", "--", *paths)
    staged = [p for p in git(cwd, "diff", "--cached", "--name-only").splitlines() if p]
    if not staged:
        raise WorkflowError("NOTHING_TO_COMMIT", f"no changes under {paths}")
    git(cwd, "commit", "-q", "-m", message)
    return head(cwd)
