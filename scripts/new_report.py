"""Scaffold a results-driven report: saved data -> figure PDFs -> report PDF.

    new-report REPORT_DIR --shared SHARED_DIR --title TITLE

Writes REPORT_DIR (Snakefile, its workflow profile, report.typ, refs.bib, one
example figure script and its sample data), which must be new or empty. Writes
SHARED_DIR's report.smk and theme.typ only where absent: they are the author's
from then on, so a second report reuses them untouched. Appends the report's build
output and references/ to the repo's .gitignore, and prints -- does not
write -- the pixi wiring, since editing a manifest means guessing its layout.

The build logic a fix would need to reach lives in the exported report-check
and report_plotting, not in these files, so the scaffold holds only taste.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from string import Template

# Typst's own fonts only: report-check fails on any warning, and Typst warns
# for every font family the building machine lacks.
THEME_TYP = """\
// Shared styling for the reports scaffolded against this directory. Written
// once by new-report and yours from then on.

#let report-theme(title: none, body) = {
  set document(title: title)
  set page(numbering: "1")
  set par(justify: true)
  set heading(numbering: "1.1")
  align(center, text(size: 18pt, weight: "bold", title))
  body
}

// fig(name) places <dir>/<name>.pdf, so a document names a figure exactly as
// its Snakefile's FIGURES does. `dir` is relative to this file: a relative
// image() path resolves against the file the call textually lives in.
#let figures-in(dir) = (name, caption: none) => figure(
  image(dir + "/" + name + ".pdf", width: 90%),
  caption: caption,
)
"""

REPORT_SMK = Template("""\
# The document rule of every report scaffolded against this directory. Each
# report's Snakefile defines FIGURES, DOCUMENT, BIB and MAX_PAGES and includes
# this file, and keeps its own `rule all`: Snakemake never takes an included
# rule as the default target. BIB = "" means the document cites a bibliography
# outside the report, so it is no input here. Written once by new-report and
# yours from then on.

import os
from pathlib import Path

SHARED = Path(str(workflow.current_basedir))
# The Typst root, given from this directory: the theme and every report's
# figures must lie under it, so widen it if a report outside it includes this
# file. Taken relative to the report (the working directory) so that no path
# in the command holds a space a shell would split on.
ROOT = os.path.relpath(SHARED / "$root")


rule document:
    input:
        f"{DOCUMENT}.typ",
        os.path.relpath(SHARED / "theme.typ"),
        *([BIB] if BIB else []),
        expand("build/figures/{name}.pdf", name=FIGURES),
    output:
        f"build/{DOCUMENT}.pdf",
    shell:
        "report-check --compile {output} --root {ROOT} --max-pages {MAX_PAGES} ."
""")
# ROOT as REPORT_SMK writes it. A ROOT rewritten in another form is not read,
# and keeping it wide enough is left to whoever rewrote it.
ROOT_LINE = re.compile(r'^ROOT = os\.path\.relpath\(SHARED / "([^"]*)"\)', re.MULTILINE)

SNAKEFILE = Template("""\
# Build DAG for $title: data/ -> build/figures/*.pdf -> build/<DOCUMENT>.pdf.
#
#     snakemake --cores all
#
# Figures read saved data. Expensive compute is a driver script beside this
# file, run by hand to write data/ once, so it has no rule here.
#
# FIGURES is the registry (figure name -> figures/plot_*.py stem) that
# report-check compares with the #fig calls in the document and the scripts on
# disk. A figure joins with its script, its entry here, and a rule whose
# inputs are the script and every data file it reads. Commands use no shell
# builtins, so they run under cmd.exe, PowerShell and bash.

FIGURES = {"example": "plot_example"}
# The document is DOCUMENT.typ, so several reports can share a directory.
DOCUMENT = "report"
# The bibliography file the build needs; "" if the document cites one outside
# this directory, or none.
BIB = "refs.bib"
# The page budget report-check holds build/<DOCUMENT>.pdf to.
MAX_PAGES = 8


rule all:
    input:
        f"build/{DOCUMENT}.pdf",


include: "$include"


rule example:
    input:
        "figures/plot_example.py",
        "data/example.npz",
    output:
        "build/figures/example.pdf",
    shell:
        "python figures/plot_example.py --data-dir data --output {output}"
""")

# Snakemake loads profiles/default/ beside the Snakefile without being asked.
PROFILE = """\
# The default ILP scheduler runs pulp's bundled CBC binary, which pulp ships
# x86_64-only on macOS, so on Apple Silicon without Rosetta the build dies with
# "Bad CPU type" as soon as two jobs are ready. A figure DAG gains nothing
# from ILP scheduling.
scheduler: greedy
"""

REPORT_TYP = Template("""\
// $title
//
// Build from this directory: snakemake --cores all

#import "$theme": figures-in, report-theme

#show: report-theme.with(title: "$typst_title")

#let fig = figures-in("$figures")

= Introduction

State the question and its answer here. The build runs on Snakemake
@koester2012.

#fig(
  "example",
  caption: [The sample data in `data/example.npz`; replace it with a result.],
)

#bibliography("refs.bib")
""")

REFS_BIB = """\
@article{koester2012,
  author  = {K{\\"o}ster, Johannes and Rahmann, Sven},
  title   = {Snakemake -- a scalable bioinformatics workflow engine},
  journal = {Bioinformatics},
  volume  = {28},
  number  = {19},
  pages   = {2520--2522},
  year    = {2012},
  doi     = {10.1093/bioinformatics/bts480},
}
"""

PLOT_EXAMPLE = '''\
"""The example figure: y against x from example.npz in --data-dir."""

import sys

import matplotlib.pyplot as plt
import numpy as np
from report_plotting import parse_cli, save


def main(argv: list[str]) -> None:
    args = parse_cli(__doc__, argv, ("--data-dir", "--output"))
    with np.load(args.data_dir / "example.npz") as data:
        x, y = data["x"], data["y"]
    fig, ax = plt.subplots(figsize=(4.5, 2.5), layout="constrained")
    ax.plot(x, y)
    ax.set_xlabel("x")
    ax.set_ylabel("sin(x)")
    save(fig, args.output)


if __name__ == "__main__":
    main(sys.argv[1:])
'''

WIRING = Template("""\
Wire it into the repo's pixi manifest (under [tool.pixi.*] in a
pyproject.toml); new-report does not edit manifests:

  [tasks]
  build-$name = { cmd = "snakemake --cores all", cwd = "$cwd" }

  [dependencies]
  typst = "*"

  [pypi-dependencies]
  snakemake = ">=8"
  agent-config = { git = "https://github.com/npeard/agent-config", tag = "vX.Y.Z" }

Replace vX.Y.Z with the agent-config release to pin. The example figure also
needs matplotlib and numpy in that environment. Add "*.pdf,references" to
codespell's skip list: build output and cited sources are not yours to spell.
""")


def npy(values: list[float]) -> bytes:
    """A 1-D float64 array in the .npy v1.0 format, so scaffolding needs no numpy."""
    header = repr({"descr": "<f8", "fortran_order": False, "shape": (len(values),)})
    # Magic (6) + version (2) + length (2) + header + "\n", padded to 64 bytes.
    header += " " * (-(11 + len(header)) % 64) + "\n"
    return (
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header.encode("latin1")
        + struct.pack(f"<{len(values)}d", *values)
    )


def write_sample_data(path: Path) -> None:
    x = [2 * math.pi * i / 63 for i in range(64)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as npz:
        npz.writestr("x.npy", npy(x))
        npz.writestr("y.npy", npy([math.sin(v) for v in x]))


def git_toplevel(path: Path) -> Path | None:
    # Not platform_paths.git_output: this stays standalone like the other
    # exported gates.
    existing = next(p for p in (path, *path.parents) if p.is_dir())
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=existing,
        capture_output=True,
        encoding="utf-8",  # git's path encoding, whatever the locale
        check=False,
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def relative(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ignore(repo: Path, report: Path) -> None:
    """Append the report's ignore lines that `.gitignore` lacks."""
    prefix = relative(report, repo)
    wanted = [f"/{prefix}/{name}/" for name in ("build", ".snakemake", "references")]
    path = repo / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [line for line in wanted if line not in text.splitlines()]
    # Appended, not rewritten, so the file's existing bytes are left alone.
    with path.open("a", encoding="utf-8", newline="\n") as file:
        if missing and text and not text.endswith("\n"):
            file.write("\n")
        file.writelines(f"{line}\n" for line in missing)


def main(argv: list[str] | None = None) -> int:
    # Escape what cp1252 stdout cannot encode; see check_ascii.main.
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("report_dir", type=Path, metavar="REPORT_DIR")
    parser.add_argument("--shared", required=True, type=Path, metavar="SHARED_DIR")
    parser.add_argument("--title", required=True)
    args = parser.parse_args(argv)
    report, shared = args.report_dir.resolve(), args.shared.resolve()

    if report.is_dir() and any(report.iterdir()):
        print(
            f"{report}: not empty; new-report writes only a new report", file=sys.stderr
        )
        return 1
    repo = git_toplevel(report)
    if repo is None:
        print(f"{report}: not inside a git repository", file=sys.stderr)
        return 1
    try:
        root = Path(os.path.commonpath([report, shared]))
    except ValueError:  # different Windows drives: no Typst root holds both
        print(f"{report} and {shared} must share a root (same drive)", file=sys.stderr)
        return 1
    smk = shared / "report.smk"
    match = ROOT_LINE.search(smk.read_text(encoding="utf-8")) if smk.exists() else None
    if match and not report.is_relative_to(fixed := (shared / match[1]).resolve()):
        print(
            f"{report}: outside ROOT {fixed} in the existing {smk}, so it could "
            "not build; widen ROOT there by hand first",
            file=sys.stderr,
        )
        return 1

    for name, text in (
        ("report.smk", REPORT_SMK.substitute(root=relative(root, shared))),
        ("theme.typ", THEME_TYP),
    ):
        if not (shared / name).exists():
            write(shared / name, text)

    write(
        report / "Snakefile",
        SNAKEFILE.substitute(
            title=args.title, include=relative(shared / "report.smk", report)
        ),
    )
    typst_title = args.title.replace("\\", "\\\\").replace('"', '\\"')
    write(
        report / "report.typ",
        REPORT_TYP.substitute(
            title=args.title,
            typst_title=typst_title,
            theme=relative(shared / "theme.typ", report),
            figures=relative(report / "build/figures", shared),
        ),
    )
    write(report / "profiles/default/config.yaml", PROFILE)
    write(report / "refs.bib", REFS_BIB)
    write(report / "figures/plot_example.py", PLOT_EXAMPLE)
    write_sample_data(report / "data/example.npz")
    ignore(repo, report)

    print(f"Scaffolded {report}; shared files in {shared}.\n")
    print(WIRING.substitute(name=report.name, cwd=relative(report, repo)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
