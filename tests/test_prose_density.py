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
