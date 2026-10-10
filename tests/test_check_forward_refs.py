"""Contract tests for scripts/check_forward_refs.py."""

from __future__ import annotations

import json
from pathlib import Path

import check_forward_refs
import pytest
from conftest import write

FIXTURES = Path(__file__).parent / "fixtures" / "forward_refs"


def violations(path: Path, capsys) -> list[tuple[str, int, str, str, int]]:
    """(file name, ref line, label, defining file name, defining line)."""
    code = check_forward_refs.main([str(path), "--json"])
    found = json.loads(capsys.readouterr().out)["violations"]
    assert code == (1 if found else 0)
    return [
        (
            Path(v["file"]).name,
            v["line"],
            v["label"],
            Path(v["defined_file"]).name,
            v["defined_line"],
        )
        for v in found
    ]


@pytest.mark.parametrize("name", ["clean.tex", "clean.typ"])
def test_allowed_references_pass(name: str, capsys):
    # Backward refs, comments, unknown labels, body -> appendix, appendix ->
    # earlier text, and forward refs to floats are all allowed.
    assert violations(FIXTURES / name, capsys) == []


def test_latex_forward_references_are_flagged_with_both_ends(capsys):
    # Comma lists are split: sec:setup and sec:result are both ahead on line 5.
    assert violations(FIXTURES / "forward.tex", capsys) == [
        ("forward.tex", 4, "sec:result", "forward.tex", 7),
        ("forward.tex", 4, "eq:late", "forward.tex", 8),
        ("forward.tex", 5, "sec:setup", "forward.tex", 6),
        ("forward.tex", 5, "sec:result", "forward.tex", 7),
        ("forward.tex", 13, "app:second", "forward.tex", 14),
    ]


def test_typst_forward_references_are_flagged(capsys):
    assert violations(FIXTURES / "forward.typ", capsys) == [
        ("forward.typ", 2, "sec:result", "forward.typ", 3),
        ("forward.typ", 6, "app:second", "forward.typ", 7),
    ]


def test_typst_appendix_label_marks_the_boundary(capsys):
    assert violations(FIXTURES / "labelled_appendix.typ", capsys) == [
        ("labelled_appendix.typ", 5, "app:y", "labelled_appendix.typ", 6),
    ]


@pytest.mark.parametrize(
    "heading", ["Appendix A: Proofs", "APPENDICES", "appendix <app>"]
)
def test_typst_heading_starting_appendix_marks_the_boundary(
    heading: str, tmp_path: Path, capsys
):
    path = write(
        tmp_path,
        "a.typ",
        f"= Intro\nSee @app:x.\n= {heading}\n== X <app:x>\nSee @app:y.\n== Y <app:y>\n",
    )
    assert violations(path, capsys) == [("a.typ", 5, "app:y", "a.typ", 6)]


def test_label_inside_a_subfigure_is_a_float(tmp_path: Path, capsys):
    path = write(
        tmp_path,
        "a.tex",
        "See \\ref{panel}.\n\\begin{subfigure}{0.5\\linewidth}\n"
        "\\label{panel}\n\\end{subfigure}\n",
    )
    assert violations(path, capsys) == []


def test_input_and_include_are_followed_in_order(capsys):
    # ch1 previews ch2 (flagged); ch2 looks back at ch1 (fine).
    assert violations(FIXTURES / "thesis" / "main.tex", capsys) == [
        ("ch1.tex", 3, "ch:two", "ch2.tex", 2),
    ]


def test_nested_include_resolves_from_the_root_directory(capsys):
    # LaTeX resolves \input against the compile directory, not the including file.
    assert violations(FIXTURES / "nested" / "main.tex", capsys) == [
        ("a.tex", 1, "sec:b", "b.tex", 1),
    ]


def test_cref_autoref_and_appendices_environment(capsys):
    # Line 2 holds a forward \Cref and \autoref; line 5 (body -> appendix) is
    # exempt; line 8 is an appendix pointing at a later appendix.
    assert violations(FIXTURES / "refcommands.tex", capsys) == [
        ("refcommands.tex", 2, "sec:one", "refcommands.tex", 3),
        ("refcommands.tex", 2, "sec:two", "refcommands.tex", 4),
        ("refcommands.tex", 8, "app:b", "refcommands.tex", 9),
    ]


def test_includegraphics_is_not_an_include(tmp_path: Path, capsys):
    path = write(
        tmp_path, "a.tex", "\\includegraphics{missing}\n\\label{x}\n\\ref{x}\n"
    )
    assert violations(path, capsys) == []


def test_missing_absolute_or_out_of_root_include_is_skipped(tmp_path: Path, capsys):
    # An absolute path is not under the root, so it cannot be re-rooted at the
    # including file's directory; it must be skipped, not raise.
    missing = Path(tmp_path.anchor, "no-such-dir-forward-refs", "gone").as_posix()
    path = write(
        tmp_path,
        "a.tex",
        f"\\input{{{missing}}}\n\\input{{../outside/gone}}\n\\ref{{x}}\n\\label{{x}}\n",
    )
    assert violations(path, capsys) == [("a.tex", 3, "x", "a.tex", 4)]


def test_text_report_format_and_exit_code(capsys):
    assert check_forward_refs.main([str(FIXTURES / "forward.typ")]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == (
        f"{FIXTURES / 'forward.typ'}:2: @ -> sec:result "
        f"(defined {FIXTURES / 'forward.typ'}:3)"
    )


def test_clean_file_prints_nothing_and_exits_zero(capsys):
    assert check_forward_refs.main([str(FIXTURES / "clean.tex")]) == 0
    assert capsys.readouterr().out == ""


def test_unsupported_suffix_is_a_usage_error(tmp_path: Path, capsys):
    assert check_forward_refs.main([str(write(tmp_path, "a.md", "x"))]) == 2


@pytest.mark.parametrize("name", ["", " ", "/", ".", ".."])
def test_empty_or_root_only_include_is_skipped(name: str, tmp_path: Path, capsys):
    path = write(tmp_path, "a.tex", f"\\input{{{name}}}\n\\ref{{x}}\n\\label{{x}}\n")
    assert violations(path, capsys) == [("a.tex", 2, "x", "a.tex", 3)]


def test_include_with_a_non_tex_suffix_tries_tex_first(tmp_path: Path, capsys):
    # LaTeX reads \input{ch1.v2} as ch1.v2.tex when that exists.
    write(tmp_path, "ch1.v2.tex", "\\ref{late}\n")
    write(tmp_path, "ch1.v2", "Not the chapter.\n")
    path = write(tmp_path, "a.tex", "\\input{ch1.v2}\n\\label{late}\n")
    assert violations(path, capsys) == [("ch1.v2.tex", 1, "late", "a.tex", 2)]


def test_include_with_a_non_tex_suffix_falls_back_to_the_bare_name(
    tmp_path: Path, capsys
):
    write(tmp_path, "ch1.v2", "\\ref{late}\n")
    path = write(tmp_path, "a.tex", "\\input{ch1.v2}\n\\label{late}\n")
    assert violations(path, capsys) == [("ch1.v2", 1, "late", "a.tex", 2)]


def containing(edited: Path, capsys) -> Path:
    """The root `--containing edited` checks."""
    check_forward_refs.main(["--containing", str(edited), "--json"])
    return Path(json.loads(capsys.readouterr().out)["root"])


ROOT = "\\begin{document}\n%s\\end{document}\n"


def chapter(repo: Path) -> Path:
    (repo / ".git").mkdir(parents=True)
    (repo / "ch").mkdir()
    return write(repo, "ch/one.tex", "One.\n")


def test_containing_an_edited_root_is_that_root(tmp_path: Path, capsys):
    write(tmp_path, "a.tex", ROOT % "\\input{main}\n")
    path = write(tmp_path, "main.tex", ROOT % "")
    assert containing(path, capsys) == path


def test_containing_follows_includes_transitively(tmp_path: Path, capsys):
    # a.tex sorts first, so only following ch/part finds main.tex.
    path = chapter(tmp_path)
    write(tmp_path, "a.tex", ROOT % "")
    write(tmp_path, "ch/part.tex", "\\input{ch/one}\n")
    main = write(tmp_path, "main.tex", ROOT % "\\input{ch/part}\n")
    assert containing(path, capsys) == main


@pytest.mark.parametrize(
    "body",
    ["% \\input{ch/one}\n", "Standalone.\n"],
    ids=["commented-out include", "sibling standalone root"],
)
def test_containing_ignores_a_root_that_does_not_include_the_file(
    body: str, tmp_path: Path, capsys
):
    path = chapter(tmp_path)
    write(tmp_path, "main.tex", ROOT % body)
    assert containing(path, capsys) == path


def test_containing_with_no_root_is_the_edited_file(tmp_path: Path, capsys):
    path = chapter(tmp_path)
    assert containing(path, capsys) == path


def test_containing_stops_at_the_git_root(tmp_path: Path, capsys):
    path = chapter(tmp_path / "repo")
    write(tmp_path, "main.tex", ROOT % "\\input{repo/ch/one}\n")
    assert containing(path, capsys) == path


def test_an_include_that_raises_oserror_is_skipped(tmp_path: Path, monkeypatch, capsys):
    write(tmp_path, "bad.tex", "\\ref{x}\n")
    write(tmp_path, "good.tex", "\\ref{x}\n")
    root = write(tmp_path, "main.tex", "\\input{bad}\n\\input{good}\n\\label{x}\n")
    real = Path.is_file

    def is_file(self):
        if self.name == "bad.tex":
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    assert violations(root, capsys) == [("good.tex", 1, "x", "main.tex", 3)]
