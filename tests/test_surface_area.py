"""Contract tests for scripts/surface_area.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import surface_area
from conftest import run_git, write

B_SOURCE = """\
from fix import a

LIMIT = a._x


def grow():
    return a.f()


class Box:
    pass


_hidden = 0
"""


@pytest.fixture
def fixture_repo(git_repo: Path) -> Path:
    """Base has module ``a``; head adds ``b``, which imports ``a`` and reads ``a._x``."""
    (git_repo / "fix").mkdir()
    write(git_repo, "fix/__init__.py", "")
    write(git_repo, "fix/a.py", "_x = 1\n\n\ndef f():\n    return _x\n")
    run_git(git_repo, "add", ".")
    run_git(git_repo, "commit", "-qm", "base")
    run_git(git_repo, "tag", "base")
    write(git_repo, "fix/b.py", B_SOURCE)
    run_git(git_repo, "add", ".")
    run_git(git_repo, "commit", "-qm", "head")
    return git_repo


def report(repo: Path, capsys) -> dict[str, Any]:
    argv = ["--repo", str(repo), "--package", "fix", "--base", "base", "--json"]
    assert surface_area.main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_new_module(fixture_repo: Path, capsys):
    assert report(fixture_repo, capsys)["new_modules"] == ["fix.b"]


def test_new_public_symbols_skip_private_and_imported_names(fixture_repo: Path, capsys):
    assert report(fixture_repo, capsys)["new_public_symbols"] == [
        "fix.b.Box",
        "fix.b.LIMIT",
        "fix.b.grow",
    ]


def test_new_import_edge(fixture_repo: Path, capsys):
    assert report(fixture_repo, capsys)["new_edges"] == [["fix.b", "fix.a"]]


def test_private_read_flags_the_new_module(fixture_repo: Path, capsys):
    flagged = report(fixture_repo, capsys)["flagged_modules"]
    assert flagged == {"fix.b": ["reads private a._x (line 3)"]}


def test_rates_per_100_net_loc(fixture_repo: Path, capsys):
    rates = report(fixture_repo, capsys)
    loc = len(B_SOURCE.splitlines())
    assert rates["net_loc"] == loc
    assert rates["public_symbols_per_100_loc"] == pytest.approx(300 / loc)
    assert rates["edges_per_100_loc"] == pytest.approx(100 / loc)


def test_all_overrides_the_underscore_rule(fixture_repo: Path, capsys):
    write(fixture_repo, "fix/c.py", '__all__ = ["shown"]\n\nshown = hidden = 1\n')
    write(fixture_repo, "fix/a.py", "from fix import c\n\n_x = c.shown\n")
    run_git(fixture_repo, "add", ".")
    run_git(fixture_repo, "commit", "-qm", "c")
    result = report(fixture_repo, capsys)
    assert "fix.c.shown" in result["new_public_symbols"]
    assert "fix.c.hidden" not in result["new_public_symbols"]
    # a is c's only importer, so c is a one-caller module.
    assert result["flagged_modules"]["fix.c"] == ["fan-in 1 (imported only by fix.a)"]


def test_parent_reexport_is_not_a_single_caller(fixture_repo: Path, capsys):
    write(fixture_repo, "fix/c.py", "shown = 1\n")
    write(fixture_repo, "fix/a.py", "from fix import c\n\n_x = c.shown\n")
    write(fixture_repo, "fix/__init__.py", "from fix.c import shown\n")
    run_git(fixture_repo, "add", ".")
    run_git(fixture_repo, "commit", "-qm", "c")
    assert "fix.c" not in report(fixture_repo, capsys)["flagged_modules"]


def test_text_report_names_every_section(fixture_repo: Path, capsys):
    argv = ["--repo", str(fixture_repo), "--package", "fix", "--base", "base"]
    assert surface_area.main(argv) == 0
    out = capsys.readouterr().out
    for heading in ("New modules", "New public symbols", "New import edges"):
        assert heading in out
    assert "fix.b: reads private a._x (line 3)" in out
