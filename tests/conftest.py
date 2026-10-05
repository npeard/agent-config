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


def dep_report(dep_updates, **changes):
    """A clean win-64 DepReport with ``changes`` applied.

    Takes the module because the hook and preflight each reach dep_updates
    through their own loaded reference.
    """
    report = dep_updates._blank(True, "win-64")
    for key, value in changes.items():
        setattr(report, key, value)
    return report


def torch_finding(dep_updates):
    """The myproject finding that motivated the check: conda torch, newer on PyPI."""
    return dep_updates.Finding(
        name="pytorch-gpu",
        pypi_name="torch",
        source="conda-forge",
        locked="2.13.0",
        candidate="2.14.0",
        candidate_source="pypi",
        wheel="win_amd64 cp313 wheel",
        spec=">=2.13",
        envs=["default"],
    )


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


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
