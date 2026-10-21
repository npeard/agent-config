"""Shared fixtures.

`scripts/` is a flat directory of modules that `pyproject.toml` exports as
console scripts, and the host hooks load some of them by file path, so tests
reach them by path rather than via an installed distribution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# Hooks `import hook_lib`; a host run puts the script dir on sys.path itself.
sys.path.insert(0, str(REPO_ROOT / "hooks"))


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


TITLE = "A demo report"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    # The space is on purpose: generated commands must survive it.
    root = tmp_path / "my repo"
    root.mkdir()
    run_git(root, "init", "-q", ".")
    return root


def scaffold(repo: Path, report: str) -> int:
    # Imported here: scripts/ joins sys.path only below this module's imports.
    import new_report

    return new_report.main(
        [
            str(repo / report),
            "--shared",
            str(repo / "reports/_shared"),
            "--title",
            TITLE,
        ]
    )


@pytest.fixture(scope="session")
def build_tools() -> None:
    """Skip locally without the tools, but fail in CI, which must build once."""
    missing = [tool for tool in ("snakemake", "typst") if not shutil.which(tool)]
    if missing:
        message = f"{', '.join(missing)} not on PATH (the report env)"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
