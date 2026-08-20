"""Tests for scripts/suppressions.py.

This file is in the checker's SELF_EXEMPT list because the fixtures below
are suppression markers as data. That exemption is pinned by a test here, so
it cannot quietly grow into a way of hiding real suppressions.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import suppressions

# Assembled at runtime so this file contains no literal marker of its own.
NOQA = "# no" + "qa"
IGNORE = "# type: " + "ignore"


def write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(body)
    return p


class TestUnjustified:
    @pytest.mark.parametrize(
        "line",
        [
            "x = 1  {noqa}",
            "x = 1  {noqa}: S307",
            "x = 1  {noqa}: E501, F401",
            "x = 1  {ignore}",
            "x = 1  {ignore}[attr-defined]",
        ],
    )
    def test_marker_without_a_reason_fails(self, tmp_path: Path, line: str):
        path = write(tmp_path, line.format(noqa=NOQA, ignore=IGNORE) + "\n")
        assert suppressions.main([str(path)]) == 1


class TestJustified:
    @pytest.mark.parametrize(
        "line",
        [
            "x = 1  {noqa}: S307 -- expr is validated, see NOTATION.md",
            "x = 1  {noqa}: E501  # long url that cannot be split",
            "x = 1  {ignore}[attr-defined] -- upstream stub is wrong",
        ],
    )
    def test_marker_with_a_reason_passes(self, tmp_path: Path, line: str):
        path = write(tmp_path, line.format(noqa=NOQA, ignore=IGNORE) + "\n")
        assert suppressions.main([str(path)]) == 0

    def test_codes_alone_are_not_a_reason(self):
        """Codes name the rule, not why breaking it is acceptable."""
        assert not suppressions.has_reason(": S307")
        assert suppressions.has_reason(": S307 -- because the input is fixed")


class TestReporting:
    def test_clean_file_passes(self, tmp_path: Path):
        assert suppressions.main([str(write(tmp_path, "x = 1\n"))]) == 0

    def test_counts_justified_suppressions(self, tmp_path: Path, capsys):
        path = write(
            tmp_path,
            f"a = 1  {NOQA}: E501 -- long url\nb = 2  {NOQA}: F401 -- re-export\n",
        )
        assert suppressions.main([str(path)]) == 0
        # Zero suppressions and two justified ones are different states.
        assert "2 justified" in capsys.readouterr().out

    def test_non_python_files_are_skipped(self, tmp_path: Path):
        p = tmp_path / "notes.md"
        p.write_text(f"example: x = 1  {NOQA}\n")
        assert suppressions.main([str(p)]) == 0


class TestSelfExemption:
    def test_exemption_list_is_exactly_the_two_data_files(self):
        """An exemption list that can grow silently is a hole, not a fix."""
        assert suppressions.SELF_EXEMPT == frozenset(
            {"scripts/suppressions.py", "tests/test_suppressions.py"}
        )

    def test_this_repo_has_no_unjustified_suppressions(self):
        assert suppressions.main([]) == 0
