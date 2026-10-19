"""The report scaffold: what new-report writes, what it leaves alone, and
that the result builds."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

import new_report
import pytest
import report_plotting
from conftest import REPO_ROOT, TITLE, scaffold


def registry(snakefile: Path) -> dict:
    # A Snakefile is not Python (`rule all:`), so only the literal is parsed.
    match = re.search(
        r"^FIGURES = (\{[^}]*\})", snakefile.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match, "no top-level FIGURES"
    return ast.literal_eval(match.group(1))


def tree(root: Path) -> set[str]:
    return {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def test_scaffold_writes_expected_tree(repo):
    assert scaffold(repo, "reports/demo") == 0
    assert {
        "reports/demo/Snakefile",
        "reports/demo/report.typ",
        "reports/demo/refs.bib",
        "reports/demo/figures/plot_example.py",
        "reports/demo/data/example.npz",
        "reports/_shared/report.smk",
        "reports/_shared/theme.typ",
    } <= tree(repo)
    assert registry(repo / "reports/demo/Snakefile") == {"example": "plot_example"}


def test_second_report_leaves_shared_untouched(repo):
    scaffold(repo, "reports/one")
    shared = repo / "reports/_shared"
    before = {p.name: p.read_bytes() for p in shared.iterdir()}
    assert scaffold(repo, "reports/two") == 0
    assert {p.name: p.read_bytes() for p in shared.iterdir()} == before
    lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(set(lines)) == 6


def test_gitignore_rerun_is_idempotent(repo):
    """A report dir deleted and rescaffolded appends nothing new."""
    scaffold(repo, "reports/demo")
    before = (repo / ".gitignore").read_text(encoding="utf-8")
    shutil.rmtree(repo / "reports/demo")
    scaffold(repo, "reports/demo")
    assert (repo / ".gitignore").read_text(encoding="utf-8") == before


def test_refuses_nonempty_report_dir(repo, capsys):
    report = repo / "reports/demo"
    report.mkdir(parents=True)
    (report / "notes.txt").write_text("mine\n", encoding="utf-8")
    assert scaffold(repo, "reports/demo") == 1
    assert "not empty" in capsys.readouterr().err
    assert tree(repo) == {"reports/demo/notes.txt"}


def test_prints_wiring_without_editing_manifests(repo, capsys):
    manifests = {"pixi.toml": "[workspace]\n", "pyproject.toml": "[project]\n"}
    for name, body in manifests.items():
        (repo / name).write_text(body, encoding="utf-8")
    scaffold(repo, "reports/demo")
    for name, body in manifests.items():
        assert (repo / name).read_text(encoding="utf-8") == body
    out = capsys.readouterr().out
    assert "snakemake --cores all" in out
    assert 'agent-config = { git = "https://github.com/npeard/agent-config"' in out


def test_figure_rule_builds(repo, build_tools):
    """The figure half alone: sample data, report_plotting, and the rule."""
    scaffold(repo, "reports/demo")
    report = repo / "reports/demo"
    subprocess.run(
        ["snakemake", "--cores", "1", "build/figures/example.pdf"],
        cwd=report,
        check=True,
        capture_output=True,
    )
    assert (report / "build/figures/example.pdf").stat().st_size > 0


def test_scaffold_builds(repo, build_tools):
    scaffold(repo, "reports/demo")
    report = repo / "reports/demo"
    result = subprocess.run(
        ["snakemake", "--cores", "1"],
        cwd=report,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (report / "build/report.pdf").stat().st_size > 0


def test_plotting_cli_requires_every_flag():
    args = report_plotting.parse_cli("doc", ["--output", "a/b.pdf"], ("--output",))
    assert args.output == Path("a/b.pdf")
    with pytest.raises(SystemExit):
        report_plotting.parse_cli("doc", [], ("--output",))


def test_plotting_save_creates_the_parent(tmp_path):
    written = []

    class Figure:
        def savefig(self, path):
            written.append(Path(path))
            Path(path).write_bytes(b"%PDF")

    output = tmp_path / "build/figures/x.pdf"
    report_plotting.save(Figure(), output)
    assert written == [output]


def test_plotting_imports_without_matplotlib():
    # A None entry makes `import matplotlib` raise, as if it were absent.
    code = "import sys; sys.modules['matplotlib'] = None; import report_plotting"
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT / "scripts",
        check=True,
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="POSIX absolute paths always share /, so only Windows drives can differ",
)
def test_refuses_dirs_without_a_common_root(repo, capsys):
    # A drive other than the repo's, which need not exist: nothing is written.
    other = "Q:" if not str(repo).upper().startswith("Q:") else "R:"
    code = new_report.main(
        [str(repo / "reports/demo"), "--shared", f"{other}/shared", "--title", TITLE]
    )
    assert code == 1
    assert "share a root" in capsys.readouterr().err
    assert tree(repo) == set()
