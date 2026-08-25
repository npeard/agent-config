"""Contract tests for scripts/check_ascii.py's exemption marker.

Fixture files are written with ``\\uXXXX`` escapes rather than literal glyphs
so this test file is itself pure ASCII and needs no exemption -- a checker
whose own test has to be exempted from the checker cannot prove much.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import check_ascii
import pytest

EM_DASH = "\u2014"
MARKER = "<!-- check-ascii: allow - demonstrates the punctuation it teaches -->"


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


class TestMarkerSkipsTheFile:
    def test_marker_with_a_reason_exempts(self, tmp_path: Path):
        path = write(tmp_path, "a.md", f"{MARKER}\n\nAn {EM_DASH} dash.\n")
        assert check_ascii.main([str(path)]) == 0

    def test_the_reason_text_is_recovered(self, tmp_path: Path):
        path = write(tmp_path, "a.md", f"{MARKER}\n")
        rest = check_ascii.marker_remainder(check_ascii.read_lines(path))
        assert check_ascii.has_reason(rest)
        assert "demonstrates" in rest


class TestMarkerWithoutAReasonFails:
    """Mirrors the house noqa rule: a suppression must say why."""

    def test_bare_marker_is_not_an_exemption(self, tmp_path: Path, capsys):
        path = write(tmp_path, "a.md", f"<!-- check-ascii: allow -->\n{EM_DASH}\n")
        assert check_ascii.main([str(path)]) == 1
        out = capsys.readouterr().out
        assert "no reason" in out
        # Naming the file is the point: pre-commit passes many paths at once,
        # so a complaint that does not say which one is unactionable.
        assert str(path) in out

    def test_bare_marker_fails_even_with_no_non_ascii(self, tmp_path: Path):
        """Otherwise a bare marker sits there unnoticed until the day it
        starts hiding something."""
        path = write(tmp_path, "a.md", "<!-- check-ascii: allow -->\nplain\n")
        assert check_ascii.main([str(path)]) == 1


class TestMarkerPlacement:
    def test_marker_below_line_ten_does_not_count(self, tmp_path: Path):
        body = "\n".join(["filler"] * 12) + f"\n{MARKER}\n{EM_DASH}\n"
        path = write(tmp_path, "a.md", body)
        assert check_ascii.main([str(path)]) == 1

    def test_python_comment_form_is_accepted(self, tmp_path: Path):
        body = f"# check-ascii: allow - unicode test data\ns = '{EM_DASH}'\n"
        assert check_ascii.main([str(write(tmp_path, "a.py", body))]) == 0


class TestUnmarkedFilesStillFail:
    def test_non_ascii_without_a_marker_fails(self, tmp_path: Path):
        path = write(tmp_path, "a.md", f"An {EM_DASH} dash.\n")
        assert check_ascii.main([str(path)]) == 1

    def test_ascii_file_passes(self, tmp_path: Path):
        assert check_ascii.main([str(write(tmp_path, "a.md", "plain\n"))]) == 0

    def test_the_checker_does_not_exempt_itself(self):
        """It documents the marker, so the literal text appears in the file.
        If that text ever drifts into the first ten lines the checker goes
        blind to its own contents, and nothing else would notice."""
        path = Path(__file__).resolve().parent.parent / "scripts" / "check_ascii.py"
        assert check_ascii.marker_remainder(check_ascii.read_lines(path)) is None


class TestMarkerMustBeInAComment:
    """Unanchored, the marker matched anywhere in the first ten lines, so a
    document that merely explained the convention exempted itself and went
    entirely unchecked."""

    def test_prose_describing_the_marker_does_not_exempt(self, tmp_path: Path):
        body = (
            "# Contributing\n\n"
            "To opt a file out, add `check-ascii: allow - reason` at the top.\n\n"
            f"An {EM_DASH} slips through here.\n"
        )
        assert check_ascii.main([str(write(tmp_path, "CONTRIBUTING.md", body))]) == 1

    @pytest.mark.parametrize("opener", ["#", "<!--", "//", "%", ";"])
    def test_each_comment_syntax_is_honoured(self, opener: str, tmp_path: Path):
        body = f"{opener} check-ascii: allow - unicode is the subject\n{EM_DASH}\n"
        assert check_ascii.main([str(write(tmp_path, "a.md", body))]) == 0

    @pytest.mark.parametrize("fence", ["```", "~~~"])
    def test_a_marker_inside_a_fence_is_an_example_not_an_instance(
        self, fence: str, tmp_path: Path
    ):
        """Showing the marker in a code block is the natural way to document
        it, so anchoring to a comment token alone was not enough."""
        body = (
            "# Contributing\n\n"
            "To opt a file out, put this at the top:\n\n"
            f"{fence}\n"
            "# check-ascii: allow - the subject is Unicode\n"
            f"{fence}\n\n"
            f"Prose with an {EM_DASH} dash.\n"
        )
        assert check_ascii.main([str(write(tmp_path, "CONTRIBUTING.md", body))]) == 1

    def test_a_marker_indented_as_a_code_block_does_not_exempt(self, tmp_path: Path):
        body = (
            "# Contributing\n\n"
            "Put this at the top:\n\n"
            "    # check-ascii: allow - the subject is Unicode\n\n"
            f"Prose with an {EM_DASH} dash.\n"
        )
        assert check_ascii.main([str(write(tmp_path, "CONTRIBUTING.md", body))]) == 1

    def test_the_real_catalog_is_still_exempt(self):
        """The one file this mechanism exists for. Guards against hardening
        the marker until nothing satisfies it."""
        repo = Path(__file__).resolve().parent.parent
        catalog = repo / "skills" / "humanizer" / "patterns.md"
        rest = check_ascii.marker_remainder(check_ascii.read_lines(catalog))
        assert rest is not None and check_ascii.has_reason(rest)
        assert check_ascii.main([str(catalog)]) == 0


class TestUnreadableFiles:
    """A pre-commit hook that tracebacks reports nothing actionable."""

    def test_invalid_utf8_is_a_violation_not_a_traceback(self, tmp_path: Path):
        path = tmp_path / "a.md"
        path.write_bytes(b"bad \xff\xfe byte\n")
        assert check_ascii.main([str(path)]) == 1

    def test_invalid_utf8_is_not_reported_as_a_permission_problem(
        self, tmp_path: Path, capsys
    ):
        path = tmp_path / "a.md"
        path.write_bytes(b"bad \xff\xfe byte\n")
        check_ascii.main([str(path)])
        assert "UTF-8" in capsys.readouterr().out

    def test_unreadable_file_is_a_violation_not_a_traceback(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """Monkeypatched rather than chmod(0o000): that does not stop root
        reading a file, and on Windows os.chmod only toggles the read-only
        bit. pixi.toml declares win-64, and pytest-as-root is normal in a
        container, so a chmod-based test fails where the code is correct.
        """
        path = write(tmp_path, "a.md", "plain\n")

        def deny(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "read_text", deny)
        assert check_ascii.main([str(path)]) == 1
        out = capsys.readouterr().out
        # An I/O failure must not masquerade as an encoding problem, or the
        # reader goes hunting for bad bytes in a file that has none.
        assert "cannot be read" in out
        assert "UTF-8" not in out


class TestNonAsciiLineSeparators:
    """`str.splitlines()` breaks on U+2028, U+2029 and U+0085, so without
    keepends those three were consumed as line breaks and never reached the
    character scan -- an ASCII gate blind to three non-ASCII codepoints, and
    exactly the kind of invisible character that survives a paste from a PDF.
    """

    @pytest.mark.parametrize("codepoint", [0x2028, 0x2029, 0x0085])
    def test_separator_is_caught(self, codepoint: int, tmp_path: Path):
        body = "line a" + chr(codepoint) + "line b\n"
        assert check_ascii.main([str(write(tmp_path, "a.md", body))]) == 1

    def test_a_plain_ascii_file_with_normal_newlines_still_passes(self, tmp_path: Path):
        """Guards against the fix over-firing on the terminators it now keeps."""
        body = "line a\nline b\r\nline c\n"
        assert check_ascii.main([str(write(tmp_path, "a.md", body))]) == 0


class TestFileEnumerationFailure:
    """`git ls-files` failing must report, not crash and not silently pass.

    Run outside a git repository this script tracebacked out of pre-commit,
    while its twin scripts/suppressions.py swallowed the identical failure
    and printed a clean bill of health for the zero files it had scanned --
    one unusable crash and one false green from the same cause.
    """

    @pytest.mark.parametrize(
        "error",
        [
            subprocess.CalledProcessError(128, ["git"]),
            FileNotFoundError(2, "No such file or directory", "git"),
        ],
    )
    def test_git_failure_is_reported_not_raised(self, monkeypatch, capsys, error):
        def fail(*args, **kwargs):
            raise error

        monkeypatch.setattr(check_ascii.subprocess, "run", fail)
        assert check_ascii.main([]) == 1
        assert "git" in capsys.readouterr().err

    def test_explicit_paths_never_consult_git(self, monkeypatch, tmp_path: Path):
        """pre-commit always passes paths, so the fallback must stay unused;
        otherwise a hook run in a submodule or a fresh checkout could fail on
        an enumeration it never needed."""

        def fail(*args, **kwargs):
            raise AssertionError("git was consulted although paths were given")

        monkeypatch.setattr(check_ascii.subprocess, "run", fail)
        assert check_ascii.main([str(write(tmp_path, "a.md", "plain\n"))]) == 0


class TestPathsWithSpaces:
    """Whitespace-splitting `git ls-files` output turned "release notes.md"
    into two paths that do not exist, and main's is_file() filter then dropped
    both without a word. -z also settles the other half of the problem: by
    default git quotes a path containing a non-ASCII byte, which an ASCII
    checker is the last tool that should skip.
    """

    def test_a_path_containing_a_space_survives_enumeration(self, monkeypatch):
        monkeypatch.setattr(
            check_ascii.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(stdout="release notes.md\0b.py\0"),
        )
        assert check_ascii.tracked_files() == ["release notes.md", "b.py"]
