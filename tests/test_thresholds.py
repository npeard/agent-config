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


class TestMultipleConditions:
    """One line can carry more than one bound, and `operator()` returned the
    first operator it found anywhere in the line -- so `n > 100` relaxed to
    `n > 10` beside a `tol < 1e-6` was read as an upper bound tightening and
    went unreported."""

    def test_each_comparison_is_read_against_its_own_operator(self):
        found = thresholds.findings(
            diff(
                "    assert n > 100 and tol < 1e-6",
                "    assert n > 10 and tol < 1e-6",
            )
        )
        assert found and "lower bound" in found[0]

    def test_a_tightened_multi_condition_line_stays_quiet(self):
        assert (
            thresholds.findings(
                diff(
                    "    assert n > 10 and tol < 1e-3",
                    "    assert n > 100 and tol < 1e-6",
                )
            )
            == []
        )

    def test_a_relaxed_second_condition_is_found(self):
        found = thresholds.findings(
            diff(
                "    assert n > 10 and tol < 1e-6",
                "    assert n > 10 and tol < 1e-3",
            )
        )
        assert found and "upper bound" in found[0]


class TestComments:
    """`shape()` hashed the whole line, so adding a trailing comment changed
    the shape and the before/after pair never matched -- the one case where
    the loosening announces itself was the one case that was missed."""

    def test_an_added_comment_does_not_break_pairing(self):
        found = thresholds.findings(
            diff("    assert err < 0.001", "    assert err < 0.5  # loosened")
        )
        assert found and "upper bound 0.001 -> 0.5" in found[0]

    def test_a_number_in_a_comment_is_not_a_bound(self):
        assert (
            thresholds.findings(
                diff("    assert err < 0.5", "    assert err < 0.5  # was 0.001")
            )
            == []
        )


class TestRenames:
    """A detector that cries wolf on a rename gets overridden, which is the
    failure this module's docstring exists to avoid."""

    def test_a_renamed_identifier_is_not_a_loosening(self):
        assert (
            thresholds.findings(
                diff("    assert v1_norm < 5", "    assert v2_norm < 5")
            )
            == []
        )

    def test_a_digit_inside_an_identifier_is_not_a_number(self):
        assert thresholds.numbers("assert v1_norm < 5") == [5.0]


class TestNamedLimits:
    """A ceiling held in a named constant is the same gate as an assertion,
    and the loosening is the same edit. Moving the ceilings out of
    tests/test_context_budget.py into scripts/audit_assets.py made every
    budget gate invisible here, because pairing required the substring
    "assert".
    """

    def test_a_raised_ceiling_is_reported(self):
        found = thresholds.findings(
            diff("CLAUDE_MD_MAX_WORDS = 1250", "CLAUDE_MD_MAX_WORDS = 1400")
        )
        assert found and "upper bound 1250.0 -> 1400.0" in found[0]

    def test_a_lowered_ceiling_is_silent(self):
        assert (
            thresholds.findings(
                diff("CLAUDE_MD_MAX_WORDS = 1250", "CLAUDE_MD_MAX_WORDS = 1000")
            )
            == []
        )

    def test_a_lowered_minimum_is_reported(self):
        found = thresholds.findings(diff("MIN_COVERAGE = 90", "MIN_COVERAGE = 50"))
        assert found and "lower bound 90.0 -> 50.0" in found[0]

    def test_a_raised_minimum_is_silent(self):
        assert thresholds.findings(diff("MIN_COVERAGE = 50", "MIN_COVERAGE = 90")) == []

    def test_other_named_limit_words_are_recognized(self):
        for name in ("WORD_LIMIT", "SIZE_CEILING", "CONTEXT_BUDGET", "MAX_RETRIES"):
            found = thresholds.findings(diff(f"{name} = 10", f"{name} = 20"))
            assert found, name

    def test_a_constant_whose_name_states_no_direction_is_ignored(self):
        """Direction has to be readable from the name. `OVERLAP_THRESHOLD`
        loosens upward and a `COVERAGE_THRESHOLD` loosens downward, so
        guessing would report half of all tightenings as loosenings."""
        assert thresholds.findings(diff("TOTAL = 1", "TOTAL = 2")) == []
        assert (
            thresholds.findings(diff("SCORE_THRESHOLD = 5", "SCORE_THRESHOLD = 9"))
            == []
        )

    def test_a_lowercase_assignment_is_ignored(self):
        """A local is not a policy constant; treating it as one would make
        every counter increment a finding."""
        assert thresholds.findings(diff("max_words = 1250", "max_words = 1400")) == []


class TestBaseRef:
    """`--base` defaulted to the literal "main" and an unknown ref exited 0,
    so on a repo whose default branch is `master` the check passed silently
    forever -- the same "gate nobody can see fail" failure it exists to find.
    """

    def test_default_branch_is_resolved_not_assumed(self, tmp_path, monkeypatch):
        import subprocess

        def run(*args: str) -> None:
            subprocess.run(
                ["git", *args], cwd=tmp_path, check=True, capture_output=True
            )

        run("init", "-q", "-b", "master", ".")
        run("config", "user.email", "test@example.invalid")
        run("config", "user.name", "test")
        (tmp_path / "f.txt").write_text("seed\n")
        run("add", "f.txt")
        run("commit", "-qm", "seed")
        monkeypatch.chdir(tmp_path)
        assert thresholds.default_branch() == "master"

    def test_an_unresolvable_base_fails_under_strict(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        assert thresholds.main(["--base", "no-such-ref", "--strict"]) == 1

    def test_an_unresolvable_base_still_reports_zero_by_default(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        assert thresholds.main(["--base", "no-such-ref"]) == 0
