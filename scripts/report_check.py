"""Gate a scaffolded report: its figure registry and, with --compile, its build.

    report-check PATH... [--compile OUTPUT --root ROOT --max-pages N]

Each PATH is a report directory or a file inside one -- the nearest ancestor
whose Snakefile has a top-level FIGURES literal -- so a pre-commit hook can
pass staged files. Each report is checked once; paths under no report are
ignored. The static check compares three lists that must agree: the FIGURES
registry (name -> figures/ script stem), the #fig("name") calls in
the document, and the figures/plot_*.py scripts. The document is
<DOCUMENT>.typ, DOCUMENT being the Snakefile's top-level string literal.

--compile also builds the document to OUTPUT with Typst and fails on any
warning, since Typst renders many mistakes at exit 0 with only a warning, and
on a page count over N. Findings print as `path: message`; exit 1 on any.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Direct import: works by file path (the script's own directory is
# sys.path[0]) and as an installed py-module; no host hook loads this through
# importlib.
from check_forward_refs import strip_typst_comments

# A Snakefile is not Python (`rule all:`), so only the literal is parsed.
REGISTRY = re.compile(r"^FIGURES\s*=\s*(\{[^}]*\})", re.MULTILINE)
DOCUMENT = re.compile(r"^DOCUMENT\s*=\s*(\"[^\"\n]*\"|'[^'\n]*')", re.MULTILINE)
# With or without `#`, since code mode (`#grid(fig("a"))`) drops it; the
# lookbehind keeps `my-fig(` or `subfig(` from counting.
FIG_CALL = re.compile(r'(?<![\w-])fig\(\s*"([^"]*)"')


def registry_text(directory: Path) -> str | None:
    snakefile = directory / "Snakefile"
    if not snakefile.is_file():
        return None
    match = REGISTRY.search(snakefile.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def document_name(directory: Path) -> str | None:
    """DOCUMENT's value, None if the line is absent, "" if it is unreadable.

    The regex admits any quoted text, and a backslash escape such as "\\N" is
    not a valid literal; "" lets the caller report that rather than traceback.
    """
    match = DOCUMENT.search((directory / "Snakefile").read_text(encoding="utf-8"))
    if not match:
        return None
    try:
        return ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return ""


def find_report(path: Path) -> tuple[Path, str, str | None] | None:
    """The report directory holding `path`, its registry and document name."""
    start = path if path.is_dir() else path.parent
    for directory in (start, *start.parents):
        if text := registry_text(directory):
            return directory, text, document_name(directory)
    return None


def static_findings(report: Path, registry: str, name: str | None) -> list[str]:
    snakefile = report / "Snakefile"
    findings = []
    if name is None:
        # An old Snakefile: check as the scaffold's default so the rest still runs.
        findings.append(f'{snakefile}: no DOCUMENT; add the line DOCUMENT = "report"')
        name = "report"
    if not name:
        return [*findings, f"{snakefile}: DOCUMENT is not a string literal"]
    document = report / f"{name}.typ"
    try:
        figures = ast.literal_eval(registry)
    except (ValueError, SyntaxError):
        figures = None
    if not isinstance(figures, dict) or not all(
        isinstance(item, str) for pair in figures.items() for item in pair
    ):
        return [*findings, f"{snakefile}: FIGURES is not a literal dict of str to str"]
    if not document.is_file():
        return [*findings, f"{document}: missing, so no #fig call can be checked"]
    text = strip_typst_comments(document.read_text(encoding="utf-8"))
    placed = set(FIG_CALL.findall(text))
    scripts = {p.stem for p in (report / "figures").glob("plot_*.py")}
    findings += [
        f'{document}: #fig("{fig}") names no FIGURES entry'
        for fig in sorted(placed - figures.keys())
    ]
    for fig, stem in sorted(figures.items()):
        if fig not in placed:
            findings.append(f'{snakefile}: FIGURES["{fig}"] is never placed by #fig')
        if stem not in scripts:
            findings.append(
                f'{snakefile}: FIGURES["{fig}"] names figures/{stem}.py, which is missing'
            )
    findings += [
        f"{report / 'figures' / stem}.py: no FIGURES entry names it"
        for stem in sorted(scripts - set(figures.values()))
    ]
    return findings


def compile_findings(
    typst: str, document: Path, output: Path, root: str, max_pages: int
) -> list[str]:
    document = str(document)
    command = [typst, "compile", "--root", root, "--diagnostic-format", "short"]

    def run(target: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*command, document, target],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    result = run(str(output))
    if result.returncode != 0 or "warning:" in result.stderr:
        return result.stderr.splitlines() or [f"{document}: typst failed"]
    # Typst writes one file per page when the name has {p}: the page count
    # comes from Typst itself rather than from parsing the PDF.
    with tempfile.TemporaryDirectory() as pages:
        paged = run(str(Path(pages) / "{p}.svg"))
        if paged.returncode != 0:
            return paged.stderr.splitlines() or [f"{document}: typst failed on SVG"]
        count = len(list(Path(pages).iterdir()))
    if count > max_pages:
        return [f"{output}: {count} pages, over the budget of {max_pages}"]
    return []


def main(argv: list[str] | None = None) -> int:
    # Escape what cp1252 stdout cannot encode; see check_ascii.main.
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="+", type=Path, metavar="PATH")
    parser.add_argument("--compile", type=Path, metavar="OUTPUT")
    parser.add_argument("--root", metavar="ROOT")
    parser.add_argument("--max-pages", type=int, metavar="N")
    args = parser.parse_args(argv)
    build = (args.compile, args.root, args.max_pages)
    if any(value is not None for value in build) and None in build:
        parser.error("--compile, --root and --max-pages go together")

    found = (find_report(path.resolve()) for path in args.paths)
    registries = {
        report: (registry, name)
        for report, registry, name in sorted(
            {hit for hit in found if hit}, key=lambda hit: hit[0]
        )
    }
    reports = list(registries)
    findings = [
        finding
        for report, (registry, name) in registries.items()
        for finding in static_findings(report, registry, name)
    ]
    if args.compile and not findings:
        typst = shutil.which("typst")
        if len(reports) != 1:
            findings.append(f"--compile needs exactly one report, got {len(reports)}")
        elif typst is None:
            findings.append("report-check: typst is not on PATH; --compile needs it")
        else:
            document = reports[0] / f"{registries[reports[0]][1]}.typ"
            findings += compile_findings(
                typst, document, args.compile, args.root, args.max_pages
            )
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
