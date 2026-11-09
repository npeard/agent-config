"""Contract tests for scripts/questions_lint.py."""

from __future__ import annotations

from pathlib import Path

import questions_lint

FIXTURES = Path(__file__).parent / "fixtures" / "questions_lint"


def qids(text: str) -> set[str]:
    return {f.qid for f in questions_lint.lint(text)}


def test_smi_compound_questions_flagged():
    flagged = qids((FIXTURES / "QUESTIONS.md").read_text(encoding="utf-8"))
    assert flagged == {"Q1", "Q1.1", "Q3"}


def test_clean_file_has_no_findings():
    assert not questions_lint.lint((FIXTURES / "clean.md").read_text(encoding="utf-8"))


def test_two_question_marks_is_multi_question():
    found = questions_lint.lint("## Q1. T\n\nIs X better? Is Y worse?\n")
    assert [(f.qid, f.rule) for f in found] == [("Q1", "multi-question")]


def test_two_framing_sentences_flagged():
    found = questions_lint.lint("## Q1. T\n\nX holds. Y holds. Does Z hold?\n")
    assert [(f.qid, f.rule) for f in found] == [("Q1", "framing")]


def test_one_framing_sentence_allowed():
    assert not questions_lint.lint("## Q1. T\n\nX holds. Does Z hold?\n")


def test_abbreviation_not_a_sentence_break():
    text = "## Q1. T\n\nDoes X beat Y (e.g. ridge) at nominal 0.5 noise vs. Z?\n"
    assert not questions_lint.lint(text)


def test_no_question_headings_is_usage_error(tmp_path, capsys):
    path = tmp_path / "QUESTIONS.md"
    path.write_text("# Nothing here\n", encoding="utf-8")
    assert questions_lint.main([str(path)]) == 2


def test_json_output_and_exit_zero_on_findings(tmp_path, capsys):
    path = tmp_path / "QUESTIONS.md"
    path.write_text("## Q1. T\n\nIs X better? Is Y worse?\n", encoding="utf-8")
    assert questions_lint.main([str(path), "--json"]) == 0
    assert '"multi-question"' in capsys.readouterr().out
