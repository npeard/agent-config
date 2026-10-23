---
name: latex-toolchain
description: Use when setting up, migrating, or debugging the build toolchain of a LaTeX project -- engine choice, VS Code build-on-save, formatter or linter install. Not for writing LaTeX prose (scientific-writing) or circuit diagrams (quantikz).
compatibility: Verified 2026-10 against conda-forge tectonic 0.17.0 (TeX Live 2022 bundle), on osx-arm64. Package names and the bundle date go stale; re-check them on a new setup.
---

# LaTeX toolchain

## Decide the engine first: try tectonic

The costly mistake is a reasoned one. A CV repo kept a system TeX Live
on the premise that "no conda-forge package ships a usable macro tree".
That is true of `texlive-core`, which ships engine binaries and no
`.cls` or `.sty` files. It is not true of **tectonic**, which was never
tried, and which builds the CV (XeLaTeX, moderncv, fontspec,
unicode-math, system fonts). It also builds a revtex paper and a
pdflatex-era Stanford thesis with beamer slides.

So before concluding a project needs a system TeX Live, test the
document against tectonic's bundle. No project setup is needed:

```bash
pixi exec -s tectonic tectonic -X compile --keep-logs main.tex
```

The first run downloads the bundle (about two minutes); later runs take
seconds. A package missing from the bundle fails loudly, naming the
file:

```text
error: q.tex:2: Package tikz Error: I did not find the tikz library
'quantikz2'. I looked for files named tikzlibraryquantikz2.code.tex ...
```

The bundle is TeX Live 2022. A package newer than that is vendored: put
its CTAN `.sty` or `.code.tex` beside the document, exclude it from
every formatter hook, and say why in the project's instructions. Fall
back to a system TeX Live only for what vendoring cannot cover, and
record which package forced it.

## Quirks a fresh setup would otherwise re-learn

Each was hit standing up the two worked examples below, and each is
commented beside the line it explains there.

| Tool           | Quirk                                                                                                                                                                |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LaTeX Workshop | Call tectonic through a pixi task (`tex-preview`). pixi runs tasks from the repo root, so `\graphicspath` resolves as under the build; pass `--keep-logs --synctex`. |
| LaTeX Workshop | `%WORKSPACE_FOLDER%` is the *first* folder of a multi-root window, not the root file's. Use `%DIR%`.                                                                 |
| latexindent    | conda-forge names it `latexindent.pl`, needs `perl-yaml-tiny` and `perl-file-homedir`, and cannot resolve on win-64 (it pins `perl *_perl5`; Windows perl differs).  |
| latexindent    | Works only under `pixi run`: called directly, its shebang finds the system perl.                                                                                     |
| latexindent    | With no project config it reindents whole files (347 of one deck's 463 lines). Add a config, or reformat in a commit of its own, before wiring it into a hook.       |
| graphviz       | Run `dot -c` before `dot`: pixi skips the post-link script that registers its output formats.                                                                        |

A Snakemake-built document also needs the greedy scheduler on Apple
Silicon; `pixi run preflight` checks for it and prints the fix.

## Worked examples

Read these commits rather than copying config from memory:

- `dispersion-engineering` `1820349` -- revtex paper; vendored
  quantikz2; tectonic for both the Snakefile and build-on-save.
- `stanford-thesis` `3e52979` (tooling) and `84e727d` (README) -- the
  same template applied to a thesis plus slides, nothing vendored.

## Red flags

| Thought                                          | Reality                                                       |
| ------------------------------------------------ | ------------------------------------------------------------- |
| "No conda package has the macros, so system TeX" | That is texlive-core. Run the tectonic command above first.   |
| "This package is too new, so tectonic is out"    | Vendor the one file.                                          |
| "`Can't locate LatexIndent/Document.pm`"         | You ran it outside `pixi run`, against the system perl.       |
| "I'll add tex-format to pre-commit now"          | Without a config it rewrites the whole tree on the first run. |
