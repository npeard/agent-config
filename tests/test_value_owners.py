"""Contract tests for scripts/value_owners.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import value_owners

SAMPLE = Path(__file__).parent / "fixtures" / "value_owners" / "sample.typ"


def owners() -> dict[str, list[str]]:
    return value_owners.owners(SAMPLE.read_text(encoding="utf-8"), ".typ")


def reported(capsys) -> dict[str, list[str]]:
    assert value_owners.main([str(SAMPLE), "--json"]) == 0
    return json.loads(capsys.readouterr().out)[str(SAMPLE)]


def test_key_in_two_exhibits_is_shared(capsys):
    assert owners()["rmse_nominal"] == ["tab-a", "fig-b", "<prose>"]
    assert reported(capsys)["rmse_nominal"] == ["tab-a", "fig-b", "<prose>"]


def test_repeat_within_one_exhibit_is_one_owner(capsys):
    assert owners()["repeat_key"] == ["fig-c"]
    assert "repeat_key" not in reported(capsys)


def test_prose_citation_not_an_exhibit(capsys):
    assert owners()["prose_and_table"] == ["tab-a", "<prose>"]
    assert "prose_and_table" not in reported(capsys)
    assert "only_prose" not in reported(capsys)


def test_unlabelled_exhibits_still_own(capsys):
    assert owners()["anon_key"] == ["<unlabelled:1>", "<unlabelled:2>"]
    assert "anon_key" in reported(capsys)


def test_text_output_counts_keys_and_shared(capsys):
    assert value_owners.main([str(SAMPLE)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("rmse_nominal")
    assert lines[-1] == "5 keys, 2 shared"


def test_latex_keys():
    tex = (
        "\\begin{document}\\begin{table}\\val{a}\\label{t}\\end{table}"
        "\\begin{figure}\\caption{\\val{a}}\\label{f}\\end{figure}\\end{document}"
    )
    assert value_owners.owners(tex, ".tex")["a"] == ["t", "f"]


def test_markdown_is_usage_error(tmp_path: Path, capsys):
    md = tmp_path / "a.md"
    md.write_text("# x\n", encoding="utf-8")
    assert value_owners.main([str(md)]) == 2
    assert "not supported" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["a.txt"])
def test_unknown_suffix_is_usage_error(tmp_path: Path, name: str):
    path = tmp_path / name
    path.write_text("x", encoding="utf-8")
    assert value_owners.main([str(path)]) == 2


def run_values(capsys, tmp_path: Path, values: dict[str, object]) -> dict[str, object]:
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    assert value_owners.main([str(SAMPLE), "--json", "--values", str(path)]) == 0
    return json.loads(capsys.readouterr().out)[str(SAMPLE)]


def test_rekeyed_quantity_is_reported(capsys, tmp_path):
    out = run_values(capsys, tmp_path, {"rmse_nominal": "0.200", "repeat_key": "0.200"})
    assert out["quantities"] == [
        {
            "value": "0.200",
            "keys": ["rmse_nominal", "repeat_key"],
            "exhibits": ["tab-a", "fig-b", "fig-c"],
        }
    ]


def test_short_or_boolean_values_are_not_quantities(capsys, tmp_path):
    out = run_values(
        capsys, tmp_path, {"rmse_nominal": "2", "repeat_key": "2", "anon_key": True}
    )
    assert out["quantities"] == []
