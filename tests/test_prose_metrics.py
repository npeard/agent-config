"""Contract tests for scripts/prose_metrics.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import prose_metrics
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "prose_metrics"
MARKUP = [FIXTURES / "sample.tex", FIXTURES / "sample.typ", FIXTURES / "sample.md"]


def report(path: Path, capsys) -> dict[str, Any]:
    assert prose_metrics.main([str(path), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


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


def test_latex_caption_is_labelled(capsys):
    captions = report(MARKUP[0], capsys)["captions"]
    assert captions[0]["label_or_index"] == "fig:12"


def test_typst_caption_falls_back_to_index(capsys):
    assert report(MARKUP[1], capsys)["captions"][0]["label_or_index"] == 1


def test_markdown_has_no_captions(capsys):
    assert report(MARKUP[2], capsys)["captions"] == []


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


def test_unbalanced_caption_is_a_parse_failure(tmp_path, capsys):
    path = write(tmp_path, "a.tex", "\\caption{never closed\n")
    assert prose_metrics.main([str(path)]) != 0


def test_human_report_exits_zero(capsys):
    assert prose_metrics.main([str(MARKUP[0])]) == 0
    assert "paragraphs" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "heading",
    [
        "\\section*{Intro}",
        "\\section[Short]{Intro}",
        "\\subsubsection{Intro}",
        "\\subsection*{Intro}",
    ],
)
def test_latex_heading_forms_are_headings_not_body(heading, tmp_path, capsys):
    path = write(tmp_path, "a.tex", f"{heading}\nBody words here.\n")
    data = report(path, capsys)
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
