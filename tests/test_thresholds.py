"""Tests for scripts/thresholds.py.

The check reports rather than gates, so what matters is that it fires on a
loosening and stays quiet on a tightening -- a detector that cries wolf on
corrections would be overridden until it was ignored.
"""

from __future__ import annotations

import pytest
import thresholds


def diff(before: str, after: str, path: str = "t.py") -> str:
    return f"+++ b/{path}\n@@\n-{before}\n+{after}\n"


class TestLoosened:
    @pytest.mark.parametrize(
        ("before", "after", "expected"),
        [
            ("    assert elapsed < 1.8", "    assert elapsed < 2.5", "upper bound"),
            ("    assert elapsed <= 10", "    assert elapsed <= 30", "upper bound"),
            ("    assert score > 0.9", "    assert score > 0.5", "lower bound"),
            ("    assert score >= 90", "    assert score >= 50", "lower bound"),
            (
                "    assert x == approx(y, abs=1e-9)",
                "    assert x == approx(y, abs=1e-3)",
                "tolerance",
            ),
        ],
    )
    def test_reports(self, before: str, after: str, expected: str):
        found = thresholds.findings(diff(before, after))
        assert found and expected in found[0]

    def test_scientific_notation_is_parsed_as_one_number(self):
        """Without it, abs=1e-9 -> abs=1e-3 parsed as 9 -> 3 and read as a
        tightening, hiding a tolerance relaxed by six orders of magnitude."""
        assert thresholds.numbers("abs=1e-3") == [1e-3]

    def test_underscored_integers(self):
        found = thresholds.findings(
            diff("    assert n < 1_000", "    assert n < 50_000")
        )
        assert found


class TestQuiet:
    @pytest.mark.parametrize(
        ("before", "after"),
        [
            ("    assert elapsed < 2.5", "    assert elapsed < 1.0"),
            ("    assert score > 0.5", "    assert score > 0.9"),
            (
                "    assert x == approx(y, abs=1e-3)",
                "    assert x == approx(y, abs=1e-9)",
            ),
            ("    assert n == 4", "    assert n == 5"),
            ("    total = 1", "    total = 2"),
        ],
    )
    def test_silent(self, before: str, after: str):
        assert thresholds.findings(diff(before, after)) == []

    def test_unrelated_lines_are_not_paired(self):
        """Matching is by shape, so two different assertions in one hunk must
        not be read as one assertion changing."""
        d = "+++ b/t.py\n@@\n-    assert a < 1\n+    assert b < 5\n"
        assert thresholds.findings(d) == []

    def test_empty_diff(self):
        assert thresholds.findings("") == []


class TestExitContract:
    """Default mode must report and still exit 0: a check that is routinely
    overridden teaches people to override it, so the verdict stays with
    review rather than with the exit code."""

    def feed(self, monkeypatch, text: str) -> None:
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO(text))

    def test_reports_a_finding_without_failing(self, monkeypatch, capsys):
        self.feed(monkeypatch, diff("    assert t < 1", "    assert t < 9"))
        assert thresholds.main(["--stdin"]) == 0
        assert "upper bound" in capsys.readouterr().out

    def test_strict_fails_on_the_same_input(self, monkeypatch, capsys):
        self.feed(monkeypatch, diff("    assert t < 1", "    assert t < 9"))
        assert thresholds.main(["--stdin", "--strict"]) == 1

    def test_strict_passes_when_clean(self, monkeypatch, capsys):
        self.feed(monkeypatch, "")
        assert thresholds.main(["--stdin", "--strict"]) == 0


class TestParsingRobustness:
    def test_identifier_with_digit_underscore_does_not_crash(self):
        """`[\\d_]*` matched the "1_" inside `v1_norm`, and float("1_") raises,
        so one such assertion aborted the entire run."""
        found = thresholds.findings(
            diff("    assert v1_norm < 1", "    assert v1_norm < 9")
        )
        assert found and "upper bound" in found[0]

    def test_underscored_numbers_still_parse(self):
        assert thresholds.numbers("assert n < 50_000") == [50000.0]

    def test_finding_is_attributed_to_the_right_file(self):
        """The path was updated at `+++` while the pending hunk was flushed at
        the next `@@`, so a hunk was reported under the following file."""
        d = (
            "+++ b/a.py\n@@\n-    assert t < 1\n+    assert t < 9\n"
            "+++ b/b.py\n@@\n-x = 1\n+x = 2\n"
        )
        found = thresholds.findings(d)
        assert found and found[0].startswith("a.py:")

    def test_multiple_files_each_reported_once(self):
        d = (
            "+++ b/a.py\n@@\n-    assert t < 1\n+    assert t < 9\n"
            "+++ b/b.py\n@@\n-    assert u < 2\n+    assert u < 8\n"
        )
        found = thresholds.findings(d)
        assert len(found) == 2
        assert {f.split(":")[0] for f in found} == {"a.py", "b.py"}
