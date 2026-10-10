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
            {"title": "Intro", "words": 15, "sentences": 2},
            {"title": "Detail", "words": 7, "sentences": 2},
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
    assert data["sections"] == [{"title": "Intro", "words": 3, "sentences": 1}]
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
        {"title": "Results", "words": 2, "sentences": 1},
        {"title": "Results", "words": 1, "sentences": 1},
    ]


def test_untitled_lead_in_comes_first(tmp_path, capsys):
    body = "Lead in.\n\n\\section{A}\nBody.\n"
    sections = report(write(tmp_path, "a.tex", body), capsys)["sections"]
    assert sections == [
        {"title": "", "words": 2, "sentences": 1},
        {"title": "A", "words": 1, "sentences": 1},
    ]


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


def sentences_of(tmp_path, capsys, body, name="a.md"):
    return report(write(tmp_path, name, body), capsys)["sentences"]


def run_of_words(n: int) -> str:
    return " ".join(["Word"] * n) + "."


def test_sentence_counts_total_and_per_section(tmp_path, capsys):
    body = "Lead one. Lead two.\n\n# A\nOne. Two. Three.\n"
    data = report(write(tmp_path, "a.md", body), capsys)
    assert data["sentences"]["count"] == 5
    assert [s["sentences"] for s in data["sections"]] == [2, 3]


def test_sentence_length_distribution(tmp_path, capsys):
    # Lengths 1..9 and 31: median 5.5, nearest-rank p90 is the ninth value, 9.
    body = " ".join(run_of_words(n) for n in [*range(1, 10), 31])
    s = sentences_of(tmp_path, capsys, body)
    assert s["count"] == 10
    assert s["median_words"] == 5.5
    assert s["p90_words"] == 9
    assert s["long_threshold_words"] == 30
    assert s["over_long_threshold"] == 1
    assert s["share_over_long_threshold"] == 0.1


def test_threshold_is_exclusive(tmp_path, capsys):
    s = sentences_of(tmp_path, capsys, run_of_words(30))
    assert s["over_long_threshold"] == 0


@pytest.mark.parametrize(
    ("name", "text", "chained"),
    [
        ("a.tex", "One; two.", 1),
        ("a.tex", "We find this: it holds.", 1),
        ("a.tex", "We find this---it holds.", 1),
        ("a.typ", "We find this \u2014 it holds.", 1),
        ("a.md", "We find this \u2014 it holds.", 1),
        ("a.md", "We find this -- it holds.", 1),
        ("a.tex", "Plain. Also plain.", 0),
        ("a.tex", "Range 3--5 is fine.", 0),
        ("a.tex", "Math $a; b$ and $c: d$ stay.", 0),
        ("a.typ", "Math $a; b$ stays.", 0),
        ("a.tex", "See Sec.~\\ref{sec:x} for that.", 0),
        ("a.tex", "Capital Note: starts here.", 0),
    ],
)
def test_chained_clauses(name, text, chained, tmp_path, capsys):
    s = sentences_of(tmp_path, capsys, text + "\n", name)
    assert s["chained_count"] == chained
    assert s["chained_clause_rate"] == chained / s["count"]


def test_longest_sentences_with_source_lines(tmp_path, capsys):
    body = (
        "\\section{S}\n"  # line 1
        "Short one.\n"  # 2
        "\n"
        "% comment\n"
        "A rather longer sentence is here now.\n"  # 5
        "Mid line starts. This second sentence is the very longest of them all\n"  # 6
        "and wraps onto line seven.\n"
        "\n"
        "Tiny. Another medium sentence here.\n"  # 9
        "Three more words. Four more words now. Five words. Six.\n"  # 10
    )
    longest = sentences_of(tmp_path, capsys, body, "a.tex")["longest"]
    assert len(longest) == 5
    assert [(x["words"], x["line"]) for x in longest[:3]] == [(15, 6), (7, 5), (4, 9)]
    assert longest[0]["text"].startswith("This second sentence")


def test_repeated_sentence_gets_its_own_line(tmp_path, capsys):
    body = "Same words here and there.\n\nSame words here and there.\n"
    longest = sentences_of(tmp_path, capsys, body)["longest"]
    assert sorted(x["line"] for x in longest) == [1, 3]


def test_no_sentences_reports_zeros(tmp_path, capsys):
    s = sentences_of(tmp_path, capsys, "")
    assert (s["count"], s["median_words"], s["p90_words"]) == (0, 0, 0)
    assert (s["chained_clause_rate"], s["longest"]) == (0, [])


def test_human_report_lists_sentence_metrics(capsys):
    assert prose_metrics.main([str(MARKUP[0])]) == 0
    out = capsys.readouterr().out
    assert "sentences: 4" in out
    assert "chained" in out
    assert "longest" in out


def test_unlocated_sentence_keeps_the_previous_line_and_cursor():
    # The opening "Bogus opening" is not in the source (say, rewritten by
    # dropped math). Its first word alone appears two lines on; jumping there
    # would misplace this sentence and every one after it.
    locate = prose_metrics.line_locator(
        "First sentence is here.\nSecond one later.\nThird has Bogus inside.\n"
    )
    assert locate("First sentence is here.") == 1
    assert locate("Bogus opening never in source.") == 1
    assert locate("Second one later.") == 2
