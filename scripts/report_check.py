"""Gate a scaffolded report: its figure registry and, with --compile, its build.

    report-check PATH... [--compile OUTPUT --root ROOT --max-pages N]

Each PATH is a report directory or a file inside one -- the nearest ancestor
whose Snakefile has a top-level FIGURES literal -- so a pre-commit hook can
pass staged files. Each report is checked once; paths under no report are
ignored. The static check compares three lists that must agree: the FIGURES
registry (name -> figures/ script stem), the #fig("name") calls in
report.typ, and the figures/plot_*.py scripts.

--compile also builds report.typ to OUTPUT with Typst and fails on any
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

# A Snakefile is not Python (`rule all:`), so only the literal is parsed.
REGISTRY = re.compile(r"^FIGURES\s*=\s*(\{[^}]*\})", re.MULTILINE)
FIG_CALL = re.compile(r'#fig\(\s*"([^"]*)"')


def registry_text(directory: Path) -> str | None:
    snakefile = directory / "Snakefile"
    if not snakefile.is_file():
        return None
    match = REGISTRY.search(snakefile.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def report_dir(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    return next((d for d in (start, *start.parents) if registry_text(d)), None)


def static_findings(report: Path) -> list[str]:
    snakefile, document = report / "Snakefile", report / "report.typ"
    try:
        figures = ast.literal_eval(registry_text(report))
    except (ValueError, SyntaxError):
        return [f"{snakefile}: FIGURES is not a literal dict"]
    placed = set(FIG_CALL.findall(document.read_text(encoding="utf-8")))
    scripts = {p.stem for p in (report / "figures").glob("plot_*.py")}
    findings = [
        f'{document}: #fig("{name}") names no FIGURES entry'
        for name in sorted(placed - figures.keys())
    ]
    for name, stem in sorted(figures.items()):
        if name not in placed:
            findings.append(f'{snakefile}: FIGURES["{name}"] is never placed by #fig')
        if stem not in scripts:
            findings.append(
                f'{snakefile}: FIGURES["{name}"] names figures/{stem}.py, which is missing'
            )
    findings += [
        f"{report / 'figures' / stem}.py: no FIGURES entry names it"
        for stem in sorted(scripts - set(figures.values()))
    ]
    return findings


def compile_findings(
    typst: str, report: Path, output: Path, root: str, max_pages: int
) -> list[str]:
    document = str(report / "report.typ")
    command = [typst, "compile", "--root", root, "--diagnostic-format", "short"]
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [*command, document, str(output)],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0 or "warning:" in result.stderr:
        return result.stderr.splitlines() or [f"{document}: typst failed"]
    # Typst writes one file per page when the name has {p}: the page count
    # comes from Typst itself rather than from parsing the PDF.
    with tempfile.TemporaryDirectory() as pages:
        subprocess.run(
            [*command, document, str(Path(pages) / "{p}.svg")],
            capture_output=True,
            check=True,
        )
        count = len(list(Path(pages).iterdir()))
    if count > max_pages:
        return [f"{output}: {count} pages, over the budget of {max_pages}"]
    return []


def main(argv: list[str] | None = None) -> int:
    # Findings name paths, and stdout may be a cp1252 console.
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

    found = (report_dir(path.resolve()) for path in args.paths)
    reports = sorted({report for report in found if report})
    findings = [finding for report in reports for finding in static_findings(report)]
    if args.compile and not findings:
        typst = shutil.which("typst")
        if len(reports) != 1:
            findings.append(f"--compile needs exactly one report, got {len(reports)}")
        elif typst is None:
            findings.append("report-check: typst is not on PATH; --compile needs it")
        else:
            findings += compile_findings(
                typst, reports[0], args.compile, args.root, args.max_pages
            )
    for finding in findings:
        print(finding)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
