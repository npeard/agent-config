"""report-check on a fresh scaffold with one planted defect per test."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import report_check
from conftest import REPO_ROOT, scaffold

REGISTRY = 'FIGURES = {"example": "plot_example"}'


@pytest.fixture
def report(repo: Path) -> Path:
    scaffold(repo, "reports/demo")
    return repo / "reports/demo"


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def check(capsys, *args: str) -> tuple[int, str]:
    code = report_check.main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_clean_scaffold_passes(report, capsys):
    assert check(capsys, str(report)) == (0, "")


def test_unregistered_fig_call_fails(report, capsys):
    edit(report / "report.typ", "#bibliography", '#fig("ghost")\n\n#bibliography')
    code, out = check(capsys, str(report))
    assert code == 1
    assert "ghost" in out
    assert "report.typ: " in out


def test_registered_but_unplaced_fails(report, capsys):
    (report / "figures/plot_unplaced.py").write_text("", encoding="utf-8")
    edit(
        report / "Snakefile",
        REGISTRY,
        'FIGURES = {"example": "plot_example", "unplaced": "plot_unplaced"}',
    )
    code, out = check(capsys, str(report))
    assert code == 1
    assert "unplaced" in out
    assert "Snakefile: " in out


def test_registry_entry_without_script_fails(report, capsys):
    (report / "figures/plot_example.py").rename(report / "figures/plot_renamed.py")
    code, out = check(capsys, str(report))
    assert code == 1
    assert "plot_example.py" in out


def test_script_without_registry_entry_fails(report, capsys):
    (report / "figures/plot_extra.py").write_text("", encoding="utf-8")
    code, out = check(capsys, str(report))
    assert code == 1
    assert "plot_extra.py: " in out


def test_files_outside_reports_ignored(repo, report, capsys):
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src/x.py").write_text("", encoding="utf-8")
    assert check(capsys, str(repo / "README.md"), str(repo / "src/x.py")) == (0, "")


def test_many_files_one_report_checked_once(report, capsys):
    (report / "figures/plot_extra.py").write_text("", encoding="utf-8")
    files = ["Snakefile", "report.typ", "figures/plot_example.py"]
    code, out = check(capsys, *(str(report / name) for name in files))
    assert code == 1
    assert out.count("plot_extra.py") == 1


def test_compile_needs_exactly_one_report(repo, report, capsys):
    scaffold(repo, "reports/other")
    code, out = check(
        capsys,
        *("--compile", "out.pdf", "--root", str(repo), "--max-pages", "8"),
        *(str(report), str(repo / "reports/other")),
    )
    assert code == 1
    assert "one report" in out


def compile_check(capsys, repo: Path, report: Path, max_pages: int):
    # Only the figure is built here: the document is what report-check builds.
    subprocess.run(
        ["snakemake", "--cores", "1", "build/figures/example.pdf"],
        cwd=report,
        check=True,
        capture_output=True,
    )
    output = str(report / "build/report.pdf")
    root = str(repo / "reports")
    return check(
        capsys,
        *("--compile", output, "--root", root, "--max-pages", str(max_pages)),
        str(report),
    )


def test_typst_warning_fails(repo, report, build_tools, capsys):
    # Typst 0.15 compiles this at exit 0, warning only.
    edit(
        report / "report.typ",
        "= Introduction",
        '#text(font: "NoSuchFont")[x]\n\n= Introduction',
    )
    code, out = compile_check(capsys, repo, report, 8)
    assert code == 1
    assert "unknown font family" in out


def test_page_budget_fails(repo, report, build_tools, capsys):
    edit(report / "report.typ", "#bibliography", "#pagebreak()\n\n#bibliography")
    code, out = compile_check(capsys, repo, report, 1)
    assert code == 1
    assert "2 pages" in out
    assert "budget of 1" in out


def test_missing_typst_is_a_clear_error(repo, report, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(repo / "no-tools-here"))
    code, out = check(
        capsys,
        *("--compile", "out.pdf", "--root", str(repo), "--max-pages", "8"),
        str(report),
    )
    assert code == 1
    assert "typst" in out
    assert "Traceback" not in out


def test_findings_survive_cp1252_stdout(tmp_path):
    """A finding names a report dir holding a character cp1252 cannot encode."""
    report = tmp_path / "03c1"
    (report / "figures").mkdir(parents=True)
    (report / "Snakefile").write_text(REGISTRY + "\n", encoding="utf-8")
    (report / "report.typ").write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/report_check.py"), str(report)],
        check=False,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert b"UnicodeEncodeError" not in result.stderr
    assert result.stdout, "the finding should reach stdout"


def test_code_mode_fig_call_counts(report, capsys):
    edit(report / "report.typ", "#bibliography", '#grid(fig("ghost"))\n#bibliography')
    code, out = check(capsys, str(report))
    assert code == 1
    assert "ghost" in out


@pytest.mark.parametrize(
    "decoy",
    [
        '// #fig("ghost")',
        '/* #fig("ghost")\n */',
        '#my-fig("ghost")',
        '#subfig("ghost")',
    ],
)
def test_commented_or_other_function_call_is_not_a_placement(report, capsys, decoy):
    edit(report / "report.typ", "#bibliography", f"{decoy}\n#bibliography")
    assert check(capsys, str(report)) == (0, "")


def test_missing_document_is_a_finding(report, capsys):
    (report / "report.typ").unlink()
    code, out = check(capsys, str(report))
    assert code == 1
    assert "report.typ" in out


@pytest.mark.parametrize(
    "registry",
    ['FIGURES = {"example"}', 'FIGURES = {"example": ["plot_example"]}'],
)
def test_malformed_registry_is_a_finding(report, capsys, registry):
    edit(report / "Snakefile", REGISTRY, registry)
    code, out = check(capsys, str(report))
    assert code == 1
    assert "FIGURES" in out


def test_failed_page_count_compile_is_a_finding(report, monkeypatch, capsys, tmp_path):
    def fake_run(command, **kwargs):
        failed = command[-1].endswith(".svg")
        return subprocess.CompletedProcess(command, int(failed), "", "boom")

    monkeypatch.setattr(report_check.subprocess, "run", fake_run)
    findings = report_check.compile_findings(
        "typst", report, tmp_path / "out.pdf", str(report), 8
    )
    assert findings
