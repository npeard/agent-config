"""The report scaffold: what new-report writes, what it leaves alone, and
that the result builds."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import new_report
import pytest
import report_check
import report_plotting
from conftest import REPO_ROOT, TITLE, scaffold


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
        "reports/demo/profiles/default/config.yaml",
        "reports/demo/report.typ",
        "reports/demo/refs.bib",
        "reports/demo/figures/plot_example.py",
        "reports/demo/data/example.npz",
        "reports/_shared/report.smk",
        "reports/_shared/theme.typ",
    } <= tree(repo)
    figures = report_check.registry_text(repo / "reports/demo")
    assert ast.literal_eval(figures) == {"example": "plot_example"}


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
    assert (report / "build/figures/example.pdf").stat().st_size > 0
    assert (report / "build/report.pdf").stat().st_size > 0


def test_two_ready_jobs_build_without_the_ilp_solver(repo, build_tools):
    """Snakemake's default ILP scheduler runs pulp's bundled CBC whenever two
    jobs are ready at once (from 9.27, even one), and pulp ships that binary
    x86_64-only on macOS: Apple Silicon without Rosetta dies with an OSError
    that Snakemake's greedy fallback does not catch. Discriminating only on
    such a machine; elsewhere CBC runs and this passes either way.
    """
    scaffold(repo, "reports/demo")
    report = repo / "reports/demo"
    with (report / "Snakefile").open("a", encoding="utf-8") as snakefile:
        snakefile.write(
            '\n\nrule extra:\n    output:\n        "build/extra.txt",\n'
            '    run:\n        Path(output[0]).write_text("")\n'
        )
    result = subprocess.run(
        ["snakemake", "--cores", "2", "build/figures/example.pdf", "build/extra.txt"],
        cwd=report,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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


def test_refuses_a_report_outside_the_existing_shared_root(repo, capsys):
    """The first report fixed ROOT at reports/; one outside could not build."""
    scaffold(repo, "reports/demo")
    before = tree(repo)
    code = new_report.main(
        [
            str(repo / "elsewhere/demo"),
            *("--shared", str(repo / "reports/_shared"), "--title", TITLE),
        ]
    )
    assert code == 1
    assert "ROOT" in capsys.readouterr().err
    assert tree(repo) == before


def test_two_reports_share_a_directory_and_a_bibliography(repo, build_tools):
    """A named document and a bibliography outside the report both build.

    BIB = "" with refs.bib gone once raised Snakemake MissingInputException.
    """
    scaffold(repo, "reports/one")
    scaffold(repo, "reports/two")
    one, two = repo / "reports/one", repo / "reports/two"
    (one / "report.typ").rename(one / "proposal.typ")
    edit_text(one / "Snakefile", 'DOCUMENT = "report"', 'DOCUMENT = "proposal"')
    shared_bib = repo / "reports/references/shared.bib"
    shared_bib.parent.mkdir()
    shutil.move(two / "refs.bib", shared_bib)
    edit_text(two / "Snakefile", 'BIB = "refs.bib"', 'BIB = ""')
    edit_text(
        two / "report.typ",
        'bibliography("refs.bib")',
        'bibliography("../references/shared.bib")',
    )
    built = subprocess.run(
        ["snakemake", "--cores", "1"],
        cwd=one,
        check=False,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    assert (one / "build/proposal.pdf").stat().st_size > 0
    assert (
        report_check.main(
            [
                *("--compile", str(one / "build/check.pdf")),
                *("--root", str(one.parent)),
                *("--max-pages", "8"),
                str(one),
            ]
        )
        == 0
    )
    # A dry run is enough for the second report: the regression was the DAG
    # failing to resolve its inputs, which -n does without a second compile.
    planned = subprocess.run(
        ["snakemake", "--cores", "1", "-n"],
        cwd=two,
        check=False,
        capture_output=True,
        text=True,
    )
    assert planned.returncode == 0, planned.stderr


def edit_text(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
