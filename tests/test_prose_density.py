"""Contract tests for scripts/prose_density.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import prose_density
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "prose_density"
MARKUP = [FIXTURES / "sample.typ", FIXTURES / "sample.tex", FIXTURES / "sample.md"]
CAPTIONED = {".typ": 2, ".tex": 2, ".md": 0}


def report(path: Path, capsys, *flags: str) -> dict[str, Any]:
    assert prose_density.main([str(path), "--json", *flags]) == 0
    return json.loads(capsys.readouterr().out)[str(path)]


@pytest.mark.parametrize("path", MARKUP, ids=lambda p: p.suffix)
class TestEveryFormat:
    def test_sections_count_only_prose(self, path: Path, capsys):
        # Comments, display math, floats, code blocks, #assert and the
        # bibliography all hold digits; none reaches a section.
        rows = {r["title"]: r for r in report(path, capsys)["sections"]}
        assert list(rows) == ["Results", "Detail", "Discussion"]
        assert [r["numbers"] for r in rows.values()] == [3, 0, 0]
        assert [r["identifiers"] for r in rows.values()] == [0, 4, 0]

    def test_numbers_split_by_region(self, path: Path, capsys):
        overall = report(path, capsys)["overall"]
        captions = CAPTIONED[path.suffix]
        assert (overall["caption_numbers"], overall["float_numbers"]) == (captions, 2)
        assert overall["prose_number_share"] == round(3 / (5 + captions), 3)

    def test_depth_folds_subsections(self, path: Path, capsys):
        rows = report(path, capsys, "--depth", "1")["sections"]
        assert [(r["title"], r["identifiers"]) for r in rows] == [
            ("Results", 4),
            ("Discussion", 0),
        ]

    def test_density_is_per_hundred_words(self, path: Path, capsys):
        row = report(path, capsys)["sections"][0]
        assert row["numbers_per_100_words"] == round(300 / row["words"], 2)


def test_thresholds_fail_the_run(capsys):
    path = str(MARKUP[0])
    assert prose_density.main([path, "--max-identifiers", "4"]) == 0
    assert prose_density.main([path, "--max-identifiers", "3"]) == 1
    assert prose_density.main([path, "--max-numbers-per-100", "1"]) == 1
    assert "Detail: 4 identifiers" in capsys.readouterr().err


def test_value_call_is_one_number():
    assert prose_density.count_numbers('at #val("r1_n6") and #fmt(x, 2)') == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("x^2 and a_{10}", 0),
        ("1e-3 to 5%", 2),
        ("3--5 runs", 2),
        ("@fig-12", 0),
        ("Q1 and R2", 0),
    ],
)
def test_what_is_a_number(text: str, expected: int):
    assert prose_density.count_numbers(text) == expected


def test_unsupported_suffix_is_usage_error(tmp_path: Path):
    other = tmp_path / "a.rst"
    other.write_text("text", encoding="utf-8")
    assert prose_density.main([str(other)]) == 2


def test_exhibits_counts_labelled_floats():
    text = (FIXTURES / "sample.typ").read_text(encoding="utf-8")
    found = prose_density.exhibits(text, ".typ")
    assert [(e.label, e.kind) for e in found] == [
        ("fig-a", "figure"),
        ("tab-a", "table"),
        (None, "figure"),
        ("tab-b", "table"),
    ]


def test_exhibits_label_forms():
    latex = r"\begin{figure}\caption{c}\label{fig:a}\end{figure}"
    assert [(e.label, e.kind) for e in prose_density.exhibits(latex, ".tex")] == [
        ("fig:a", "figure")
    ]
    markdown = "text\n\n| a | b |\n| - | - |\n| 1 | 2 |\n"
    assert [(e.label, e.kind) for e in prose_density.exhibits(markdown, ".md")] == [
        (None, "table")
    ]


@pytest.mark.parametrize(
    ("kind", "table", "cells"),
    [
        (".typ", "#table(columns: 3, table.header([x], [y], [z]), [a], [b], [c])", 3),
        (
            ".tex",
            "\\begin{table}\n x & y \\\\ \\midrule\n a & b \\\\ c & d \\\\\n\\end{table}",
            4,
        ),
        (".md", "| x | y |\n| - | - |\n| a | b |\n| c | d |\n", 4),
    ],
)
def test_table_cells_excludes_header(kind: str, table: str, cells: int):
    assert prose_density.analyze(table, kind, None)["document"]["table_cells"] == cells


def test_document_block_in_json(capsys):
    document = report(MARKUP[0], capsys)["document"]
    assert document == {
        "exhibits": 4,
        "figures": 2,
        "tables": 2,
        "unlabelled": 1,
        "table_cells": 10,
    }


def typst_cells(text: str) -> int:
    return prose_density.analyze(text, ".typ", None)["document"]["table_cells"]


def test_typst_caption_is_not_a_cell():
    figure = "#figure(table(columns: 2, [a], [b], [c], [d]), caption: [A caption.])"
    assert typst_cells(figure) == 4


def test_typst_counts_every_positional_cell_kind():
    # Spread rows cannot be counted statically, so they add nothing.
    table = '#table(columns: 4, table.header([h]), [a], "s", val("k"), ..rows)'
    assert typst_cells(table) == 3


def test_typst_rules_are_not_cells():
    table = "#table(columns: 2, table.hline(), [a], table.vline(), [b])"
    assert typst_cells(table) == 2


def test_typst_unbalanced_table_does_not_crash():
    assert typst_cells('#table(columns: 1, [a], "(")') >= 0
