"""Shared fixtures.

`scripts/` is not a package and is deliberately kept import-free of project
structure (each script is meant to be copied into other repos verbatim), so
tests reach it by path rather than via an installed distribution.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A throwaway repo with one commit.

    An initial commit is required because `rev-parse --abbrev-ref HEAD`
    fails on a repo with no history, which would make branch detection
    error rather than report.
    """
    run_git(tmp_path, "init", "-q", "-b", "main", ".")
    run_git(tmp_path, "config", "user.email", "test@example.invalid")
    run_git(tmp_path, "config", "user.name", "test")
    (tmp_path / "README.md").write_text("seed\n")
    run_git(tmp_path, "add", "README.md")
    run_git(tmp_path, "commit", "-qm", "seed")
    return tmp_path
