"""Tests for scripts/suppressions.py.

Every fixture marker below is assembled from pieces at runtime, so this file
contains no literal suppression of its own and needs no exemption from the
checker. That is deliberate: the checker and its test used to be exempt
wholesale, which is a blanket file-level pass in the two files nobody would
audit for one, and neither file tripped the check anyway.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

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


class TestTheCheckerChecksItself:
    """With the self-exemption gone this covers the checker's own source and
    this file too, which is the point: a marker that drifts into either one
    is now reported by name and line instead of being waved through."""

    def test_this_repo_has_no_unjustified_suppressions(self):
        assert suppressions.main([]) == 0


class TestFileEnumerationFailure:
    """The same contract as tests/test_check_ascii.py's.

    These two helpers are deliberate copies, and they had drifted: one
    tracebacked when `git ls-files` failed, the other returned an empty list
    and reported "0 unjustified" -- a green check that had read nothing.
    """

    @pytest.mark.parametrize(
        "error",
        [
            subprocess.CalledProcessError(128, ["git"]),
            FileNotFoundError(2, "No such file or directory", "git"),
        ],
    )
    def test_git_failure_is_reported_not_a_false_pass(self, monkeypatch, capsys, error):
        def fail(*args, **kwargs):
            raise error

        monkeypatch.setattr(suppressions.subprocess, "run", fail)
        assert suppressions.main([]) == 1
        assert "git" in capsys.readouterr().err

    def test_explicit_paths_never_consult_git(self, monkeypatch, tmp_path: Path):
        def fail(*args, **kwargs):
            raise AssertionError("git was consulted although paths were given")

        monkeypatch.setattr(suppressions.subprocess, "run", fail)
        assert suppressions.main([str(write(tmp_path, "x = 1\n"))]) == 0


class TestPathsWithSpaces:
    """Same hole as tests/test_check_ascii.py's: whitespace-splitting
    `git ls-files` output silently dropped any tracked path with a space in
    it, and a checker that skips a file quietly is worse than one that fails.
    -z also stops git quoting paths with non-ASCII bytes, which would be
    skipped the same way.
    """

    def test_a_path_containing_a_space_survives_enumeration(self, monkeypatch):
        monkeypatch.setattr(
            suppressions.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(stdout="my module.py\0b.py\0"),
        )
        assert suppressions.tracked_files() == ["my module.py", "b.py"]


class TestEveryMarkerOnTheLine:
    """One justified marker used to launder an unjustified one.

    scan() stopped at the first pattern that matched a line, and every
    pattern's remainder ran to end-of-line -- so the reason belonging to a
    later marker was read as the earlier marker's reason, and a bare
    suppression sitting beside a documented one was never reported.
    """

    def test_a_reasoned_marker_does_not_justify_a_bare_one(
        self, tmp_path: Path, capsys
    ):
        line = f"x = 1  {IGNORE}  {NOQA}: E501 -- url cannot be split\n"
        assert suppressions.main([str(write(tmp_path, line))]) == 1
        out = capsys.readouterr().out
        assert "type: ignore" in out
        assert "1 unjustified, 1 justified" in out

    def test_two_bare_markers_are_two_complaints(self, tmp_path: Path, capsys):
        line = f"x = 1  {IGNORE}  {NOQA}: E501\n"
        assert suppressions.main([str(write(tmp_path, line))]) == 1
        assert "2 unjustified" in capsys.readouterr().out

    def test_two_reasoned_markers_both_count(self, tmp_path: Path, capsys):
        line = (
            f"x = 1  {IGNORE}[attr-defined] -- upstream stub is wrong  "
            f"{NOQA}: E501 -- and the url cannot be split\n"
        )
        assert suppressions.main([str(write(tmp_path, line))]) == 0
        assert "2 justified" in capsys.readouterr().out

    def test_a_hash_inside_a_reason_is_not_a_second_marker(
        self, tmp_path: Path, capsys
    ):
        """Guards the truncation from over-firing: an issue reference is the
        most likely thing to find in a reason."""
        line = f"x = 1  {NOQA}: E501 -- see issue #42, upstream fix pending\n"
        assert suppressions.main([str(write(tmp_path, line))]) == 0
        assert "1 justified" in capsys.readouterr().out


# Assembled for the same reason the line-level fixtures are: a literal
# directive here would be a real suppression in this file.
FILE_LEVEL = (
    "# ruff: no" + "qa",
    "# ruff: no" + "qa: E501",
    "# flake8: no" + "qa",
    "# mypy: ignore-" + "errors",
    "# mypy: disable-error-" + 'code="attr-defined, union-attr"',
)


class TestFileLevelDirectives:
    """A file-level directive switches a rule off for an entire file, so it
    is strictly broader than any line marker -- and it was the one form this
    check could not see at all. The line-level noqa pattern requires the
    marker to follow its `#` directly, so `ruff: no` + `qa` matched nothing
    and disabling ruff for a whole file cost nothing.
    """

    @pytest.mark.parametrize("directive", FILE_LEVEL)
    def test_a_bare_directive_fails(self, tmp_path: Path, directive: str):
        assert suppressions.main([str(write(tmp_path, directive + "\n"))]) == 1

    @pytest.mark.parametrize("directive", FILE_LEVEL)
    def test_a_directive_with_a_reason_passes(self, tmp_path: Path, directive: str):
        body = f"{directive} -- vendored file, upstream owns its style\n"
        assert suppressions.main([str(write(tmp_path, body))]) == 0

    def test_the_complaint_names_the_directive_not_just_noqa(
        self, tmp_path: Path, capsys
    ):
        """The reader has to see that the scope is the file, not the line."""
        path = write(tmp_path, FILE_LEVEL[0] + "\n")
        assert suppressions.main([str(path)]) == 1
        assert "ruff: no" + "qa" in capsys.readouterr().out


def write_config(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


class TestConfigFileSuppressions:
    """Silencing a rule in the linter's own config is the cheapest
    suppression there is -- one line, no source file touched, permanent --
    and it was the one channel this check did not watch, because it skipped
    everything that was not a .py file.
    """

    def test_a_bare_ignore_list_fails(self, tmp_path: Path, capsys):
        body = '[tool.ruff.lint]\nignore = ["E501", "S101"]\n'
        assert suppressions.main([str(write_config(tmp_path, "pyproject.toml", body))])
        assert "ignore" in capsys.readouterr().out

    def test_a_trailing_comment_is_a_reason(self, tmp_path: Path):
        body = '[tool.ruff.lint]\nignore = ["E501"]  # the formatter owns width\n'
        path = write_config(tmp_path, "pyproject.toml", body)
        assert suppressions.main([str(path)]) == 0

    def test_a_comment_block_above_is_a_reason(self, tmp_path: Path):
        """Where a reason for a multi-entry list naturally goes."""
        body = (
            "[tool.ruff.lint]\n"
            "# The formatter owns line width, so E501 would only ever fire\n"
            "# on strings it cannot split.\n"
            'ignore = ["E501"]\n'
        )
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 0

    def test_a_comment_inside_a_multiline_array_is_a_reason(self, tmp_path: Path):
        body = '[tool.ruff.lint]\nignore = [\n    "E501",  # long urls\n]\n'
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 0

    def test_a_multiline_array_with_no_comment_fails(self, tmp_path: Path):
        body = '[tool.ruff.lint]\nignore = [\n    "E501",\n    "S101",\n]\n'
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 1

    def test_per_file_ignores_entries_need_a_reason(self, tmp_path: Path):
        """The keys in that table are file globs, so watching key names alone
        would leave the whole table unwatched."""
        body = '[tool.ruff.lint.per-file-ignores]\n"tests/**" = ["S101"]\n'
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 1

    def test_per_file_ignores_entry_with_a_reason_passes(self, tmp_path: Path):
        body = (
            "[tool.ruff.lint.per-file-ignores]\n"
            '"tests/**" = ["S101"]  # asserting is what a test is for\n'
        )
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 0

    def test_a_quoted_glob_key_holding_a_space_is_still_seen(self, tmp_path: Path):
        """A per-file-ignores key is a path glob, and a path may contain a
        space. Reading the key as one unbroken run of non-space characters
        made such an entry invisible -- the same class of hole as splitting
        `git ls-files` output on whitespace."""
        body = '[tool.ruff.lint.per-file-ignores]\n"my tests/**" = ["S101"]\n'
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 1

    def test_mypy_config_keys_are_watched(self, tmp_path: Path):
        body = '[tool.mypy]\ndisable_error_code = ["attr-defined"]\n'
        path = write_config(tmp_path, "pyproject.toml", body)
        assert suppressions.main([str(path)]) == 1

    def test_ini_syntax_is_read_the_same_way(self, tmp_path: Path):
        """setup.cfg and .flake8 are INI, but `key = value` with `#`
        comments reads identically, so one line-based scan covers both."""
        assert (
            suppressions.main(
                [str(write_config(tmp_path, ".flake8", "[flake8]\nignore = E501\n"))]
            )
            == 1
        )

    def test_a_path_exclusion_is_not_a_rule_suppression(self, tmp_path: Path):
        """ "These files are not ours to lint" is a different claim from "this
        rule does not apply to our code". Demanding a rationale for excluding
        a build directory is the noise that gets a check ignored."""
        body = 'extend-exclude = ["*.md"]\nexclude = ["build"]\n'
        assert suppressions.main([str(write_config(tmp_path, "ruff.toml", body))]) == 0

    def test_a_key_that_merely_contains_ignore_is_not_flagged(self, tmp_path: Path):
        """codespell's dictionary is not a rule suppression."""
        body = '[tool.codespell]\nignore-words-list = "aaa,bbb"\n'
        assert (
            suppressions.main([str(write_config(tmp_path, "pyproject.toml", body))])
            == 0
        )

    def test_an_unrelated_toml_is_not_scanned(self, tmp_path: Path):
        """Named config files, not every .toml: a data file with an `ignore`
        key of its own is not a linter config, and scanning them all turns
        this check into noise."""
        body = 'ignore = ["not a linter rule"]\n'
        assert suppressions.main([str(write_config(tmp_path, "data.toml", body))]) == 0

    def test_the_fallback_scan_reaches_config_files(self):
        """pre-commit passes only the files its `types` filter selected, so
        the tracked-file fallback is the path that actually sees a config
        file; enumerating only *.py would have left this fix inert."""
        assert any(
            Path(f).name in suppressions.CONFIG_FILENAMES
            for f in suppressions.tracked_files()
        )


class TestUnreadableFiles:
    """An unreadable file cannot be shown free of suppressions, so skipping
    it quietly is the same false green that the enumeration failure was.
    scripts/check_ascii.py already reports this case; these two decided it
    differently for no reason anyone recorded.
    """

    def test_an_unreadable_source_file_is_reported(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        path = write(tmp_path, "x = 1\n")

        def deny(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "read_text", deny)
        assert suppressions.main([str(path)]) == 1
        assert "cannot be read" in capsys.readouterr().out

    def test_an_unreadable_config_file_is_reported(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        path = write_config(tmp_path, "ruff.toml", "[lint]\n")

        def deny(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "read_text", deny)
        assert suppressions.main([str(path)]) == 1
        assert "cannot be read" in capsys.readouterr().out
