"""Contract tests for scripts/prose_metrics.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import prose_metrics
import pytest
from conftest import write

FIXTURES = Path(__file__).parent / "fixtures" / "prose_metrics"
MARKUP = [FIXTURES / "sample.tex", FIXTURES / "sample.typ", FIXTURES / "sample.md"]


def report(path: Path, capsys) -> dict[str, Any]:
    assert prose_metrics.main([str(path), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("path", MARKUP, ids=lambda p: p.suffix)
class TestEveryFormat:
    def test_only_body_prose_is_a_paragraph(self, path: Path, capsys):
        # Preamble, comment, display math, figure and fenced code are excluded.
        assert report(path, capsys)["paragraphs"]["count"] == 2

    def test_section_totals(self, path: Path, capsys):
        sections = report(path, capsys)["sections"]
        assert sections == [
            {"title": "Intro", "words": 15},
            {"title": "Detail", "words": 7},
        ]

    def test_sentence_counts(self, path: Path, capsys):
        sentences = report(path, capsys)["sentences_per_paragraph"]
        assert (sentences["median"], sentences["max"]) == (2, 2)


@pytest.mark.parametrize("path", MARKUP[:2], ids=lambda p: p.suffix)
class TestCaptions:
    def test_nested_delimiters_are_balanced(self, path: Path, capsys):
        captions = report(path, capsys)["captions"]
        assert [c["words"] for c in captions] == [12]

    def test_shared_numerics_skip_refs_and_bare_digits(self, path: Path, capsys):
        # 12 is in the caption but only reaches the body through a reference,
        # and the bare 2 is in both.
        assert report(path, capsys)["shared_numerics"] == ["3.5"]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (MARKUP[0], ["fig:12"]),  # the LaTeX \\label in its float
        (MARKUP[1], [1]),  # Typst has no labels here, so the index
        (MARKUP[2], []),  # Markdown has no captions
    ],
    ids=["latex", "typst", "markdown"],
)
def test_caption_labels(path: Path, expected, capsys):
    captions = report(path, capsys)["captions"]
    assert [c["label_or_index"] for c in captions] == expected


def test_inline_math_is_one_word_and_commands_keep_arguments(tmp_path, capsys):
    path = write(tmp_path, "a.tex", "\\emph{one} $x + y = z$ two\n")
    assert report(path, capsys)["paragraphs"]["max_words"] == 3


def test_file_without_begin_document_is_all_body(tmp_path, capsys):
    path = write(tmp_path, "frag.tex", "First para here.\n\nSecond para here.\n")
    assert report(path, capsys)["paragraphs"]["count"] == 2


def test_budgets_flag_long_paragraphs(tmp_path, capsys):
    body = " ".join(["word"] * 121) + "\n\n" + "One. Two. Three. Four. Five. Six.\n"
    data = report(write(tmp_path, "a.md", body), capsys)
    assert data["paragraphs"]["over_budget"] == 1
    assert data["paragraphs"]["budget_words"] == 120
    assert data["sentences_per_paragraph"]["over_budget"] == 1
    assert data["sentences_per_paragraph"]["budget"] == 5


def test_unbalanced_caption_still_reports(tmp_path, capsys):
    # The contract is exit 0 whenever the file is readable.
    path = write(tmp_path, "a.tex", "Body here.\n\n\\caption{never closed\n")
    assert prose_metrics.main([str(path)]) == 0


def test_human_report_exits_zero(capsys):
    assert prose_metrics.main([str(MARKUP[0])]) == 0
    assert "paragraphs" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    ("name", "heading"),
    [
        ("a.tex", "\\section*{Intro}"),
        ("a.tex", "\\section[Short]{Intro}"),
        ("a.tex", "\\subsubsection{Intro}"),
        ("a.tex", "\\subsection*{Intro}"),
        ("a.tex", "\\chapter{Intro}"),
        ("a.typ", "=== Intro"),
        ("a.md", "### Intro"),
    ],
)
def test_heading_forms_are_headings_not_body(name, heading, tmp_path, capsys):
    data = report(write(tmp_path, name, f"{heading}\nBody words here.\n"), capsys)
    assert data["sections"] == [{"title": "Intro", "words": 3}]
    assert data["paragraphs"]["count"] == 1


@pytest.mark.parametrize("env", ["gather", "multline", "eqnarray", "subequations"])
def test_more_display_math_environments_are_dropped(env, tmp_path, capsys):
    body = f"\\begin{{{env}*}}\nx = y\n\\end{{{env}*}}\n\nBody here.\n"
    path = write(tmp_path, "a.tex", body)
    assert report(path, capsys)["paragraphs"]["count"] == 1


def _shared(tmp_path, capsys, literal):
    body = f"\\caption{{Value {literal} here.}}\n\nValue {literal} here.\n"
    return report(write(tmp_path, "a.tex", body), capsys)["shared_numerics"]


def test_range_dashes_are_not_signs(tmp_path, capsys):
    assert _shared(tmp_path, capsys, "13--15") == ["13", "15"]
    assert _shared(tmp_path, capsys, "13-15") == ["13", "15"]


def test_a_leading_minus_is_a_sign(tmp_path, capsys):
    assert _shared(tmp_path, capsys, "-0.5") == ["-0.5"]
    assert _shared(tmp_path, capsys, "$10^{-31}$") == ["-31", "10"]


def test_unmatched_typst_figure_still_reports(tmp_path, capsys):
    path = write(tmp_path, "a.typ", 'Before it.\n\n#figure(image("x.png"\n\nLost.\n')
    assert report(path, capsys)["paragraphs"]["count"] == 1


def test_latex_line_break_with_spacing_is_not_display_math(tmp_path, capsys):
    body = "Alpha one\\\\[2pt] beta two.\n\nGamma $x$ \\[ y \\] delta.\n"
    data = report(write(tmp_path, "a.tex", body), capsys)
    assert data["paragraphs"]["count"] == 2
    assert data["paragraphs"]["max_words"] == 4


@pytest.mark.parametrize(
    ("name", "comment"), [("a.tex", "%"), ("a.typ", "//")], ids=["tex", "typ"]
)
class TestComments:
    def test_comment_only_line_does_not_split_a_paragraph(
        self, name, comment, tmp_path, capsys
    ):
        body = f"One two.\n{comment} note\nThree four.\n"
        data = report(write(tmp_path, name, body), capsys)
        assert data["paragraphs"]["count"] == 1
        assert data["paragraphs"]["max_words"] == 4

    def test_trailing_comment_keeps_the_text(self, name, comment, tmp_path, capsys):
        body = f"One two. {comment} gone away\n"
        data = report(write(tmp_path, name, body), capsys)
        assert data["paragraphs"]["max_words"] == 2


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("a.tex", "Before it.\n\\begin{equation}\nx\n\\end{equation}\nafter it.\n"),
        ("a.tex", "Before it.\n\\[\nx\n\\]\nafter it.\n"),
        ("a.tex", "Before it.\n\\begin{figure}\nx\n\\end{figure}\nafter it.\n"),
        ("a.typ", "Before it.\n$ x = y $\nafter it.\n"),
        ("a.typ", 'Before it.\n#figure(image("x.png"))\nafter it.\n'),
    ],
)
def test_removed_block_inside_a_paragraph_does_not_split_it(
    name, body, tmp_path, capsys
):
    assert report(write(tmp_path, name, body), capsys)["paragraphs"]["count"] == 1


def test_duplicate_titles_stay_distinct_in_document_order(tmp_path, capsys):
    body = "\\section{Results}\nOne two.\n\n\\subsection{Results}\nThree.\n"
    sections = report(write(tmp_path, "a.tex", body), capsys)["sections"]
    assert sections == [
        {"title": "Results", "words": 2},
        {"title": "Results", "words": 1},
    ]


def test_untitled_lead_in_comes_first(tmp_path, capsys):
    body = "Lead in.\n\n\\section{A}\nBody.\n"
    sections = report(write(tmp_path, "a.tex", body), capsys)["sections"]
    assert sections == [{"title": "", "words": 2}, {"title": "A", "words": 1}]


def test_zero_word_paragraphs_are_dropped(tmp_path, capsys):
    path = write(tmp_path, "a.tex", "\\maketitle\n\nBody here.\n")
    assert report(path, capsys)["paragraphs"]["count"] == 1


def test_environment_names_are_not_words(tmp_path, capsys):
    body = "\\begin{abstract}\nOne two.\n\\end{abstract}\n"
    assert (
        report(write(tmp_path, "a.tex", body), capsys)["paragraphs"]["max_words"] == 2
    )


def test_typst_setup_lines_are_not_prose(tmp_path, capsys):
    body = (
        '#set text(\n  size: 11pt,\n)\n#show: foo\n#import "x.typ": y\n'
        "#let z = 1\n\nBody here.\n"
    )
    assert report(write(tmp_path, "a.typ", body), capsys)["paragraphs"]["count"] == 1


@pytest.mark.parametrize("env", ["wrapfigure", "sidewaysfigure", "subfigure"])
def test_captions_in_other_floats_are_not_body(env, tmp_path, capsys):
    body = f"Body here.\n\n\\begin{{{env}}}\n\\caption{{A cap.}}\n\\end{{{env}}}\n"
    data = report(write(tmp_path, "a.tex", body), capsys)
    assert data["paragraphs"]["count"] == 1
    assert [c["words"] for c in data["captions"]] == [2]


def test_brackets_inside_math_do_not_unbalance_a_caption(tmp_path, capsys):
    body = '#figure(image("x.png"), caption: [Range $[0, 1)$ here.])\n\nBody.\n'
    data = report(write(tmp_path, "a.typ", body), capsys)
    assert [c["words"] for c in data["captions"]] == [3]
    assert data["paragraphs"]["count"] == 1


def test_display_math_in_the_middle_of_a_line_is_dropped(tmp_path, capsys):
    path = write(tmp_path, "a.tex", "Before \\[ x = y \\] after.\n")
    assert report(path, capsys)["paragraphs"]["max_words"] == 2
