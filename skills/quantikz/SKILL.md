---
name: quantikz
description: Use when drawing, editing, or debugging quantum circuit diagrams in LaTeX with the quantikz / quantikz2 package (TikZ-based) - gates, controls, measurements, wire bundles, gategroup highlighting, slicing, multi-circuit alignment (align equals at), per-gate and global styling, custom gate shapes, and compile errors like "cells not found" or misaligned equals signs.
---

# Quantikz (quantikz2) Quantum Circuit Diagrams

## Overview

Quantikz is a TikZ-based LaTeX package for typesetting quantum circuits. Circuits
are a matrix: cells separated by `&`, rows by `\\`. This skill targets **quantikz2**
(the current `1.x` series); prefer it over the legacy QCircuit/`tikzcd` notation.

Preamble:
```latex
\usepackage{tikz}
\usetikzlibrary{quantikz2}
```

Each circuit goes in a `quantikz` environment (use it, not `tikzcd`):
```latex
\begin{quantikz}
  \lstick{$\ket{0}$} & \gate{H} & \ctrl{1} & \meter{} \\
                     & \gate{X} & \targ{}  &
\end{quantikz}
```

## When to Use

- Building or refining a quantum-circuit figure in a paper/notes.
- Adding gates, controls, measurements, wire bundles, or wave (`...`) wires.
- Highlighting regions (`\gategroup`), slicing into time steps (`\slice`).
- Aligning several circuits around an `=`/`\approx` sign across `quantikz` blocks.
- Custom gate styling (color/fill/shape) or defining new single-qubit gate shapes.
- Debugging compile errors: "cells not found", misaligned equals, stray text in a cell.

## The Five Rules That Prevent Most Errors

1. **A gate command must be the FIRST command in its cell.** Wire-type changes
   (`\setwiretype`, `\wireoverride`, `\wire`, `\qwbundle`) come *after* the gate.
   Stray text in a cell almost always means a gate wasn't first.
2. **Always put the trailing `&` after the last gate in a row**, or its output
   wire won't be drawn.
3. **The last row must NOT end with `\\`.** Ending it breaks slicing/gategroup
   ("cells not found") errors.
4. **For slicing/gategroups, every row must have the same number of cells.**
   Pad short rows with extra `&` -- including `\wave{}` rows, which still need the
   same `&` count as the others even though the wave spans the whole row.
5. **Commands that look parameterless still need `{}`:** `\targ{}`, `\control{}`,
   `\meter{}`, `\targX{}`. Omitting the braces gives very odd output.

## Quick Reference (most-used commands)

| Need | Command |
|------|---------|
| Box gate (label in math mode) | `\gate{H}`, multi-qubit `\gate[2]{U}` |
| Filled / open control | `\ctrl{n}` / `\octrl{n}` (n = rows down, may be negative) |
| Control dot, no wire | `\control{}` / `\ocontrol{}` |
| NOT target / swap target | `\targ{}` / `\targX{}` |
| Swap gate | `\swap{n}` (paired with `\targX{}`) |
| Measurement | `\meter{}`, `\metercw{}`, `\measure{l}`, `\meterD{l}` |
| Phase dot | `\phase{\alpha}` |
| Left/mid/right wire label | `\lstick{..}`, `\midstick[n]{..}`, `\rstick{..}` (text mode) |
| Span label over n wires | `\lstick[3]{input}` |
| Highlight a region | `\gategroup[n,steps=m,style={..},background]{label}` (n = rows; see example below) |
| Time-step divider | `\slice{title}` or env option `slice all` |
| `...` continuation row | `\wave{}` then `\setwiretype{q}` if a wire is wanted |
| Inline `...` / text on wire | `\push{\cdots}`, `\push{X}` |
| Invisible spacers | `\ghost{H}` (vertical), `\phantomgate{..}` (horizontal wire), `\hphantomgate{..}` |
| Dirac notation (no math mode) | `\ket{0}`, `\bra{0}`, `\proj{0}`, `\braket{0}{1}` |

## Worked Example: highlighted region (`\gategroup`)

Place `\gategroup` in the cell at the **top-left** corner of the region; `n` rows
down and `steps=` columns right define the box. `dashed`, `rounded corners`,
`fill=`, `inner xsep=`/`inner ysep=` are plain TikZ keys passed through `style=`.
`background` is **required** whenever the box has a `fill` (else it covers the wires):

```latex
\begin{quantikz}
  \lstick{$\ket{0}$} & \gate{H}
    & \ctrl{1}\gategroup[2,steps=2,
        style={dashed, rounded corners, fill=blue!20, inner xsep=2pt},
        background,
        label style={anchor=north, yshift=-0.2cm}]{entangle}
    & \gate{X} & \meter{} \\
  \lstick{$\ket{0}$} & & \targ{} & \ctrl{-1} &
\end{quantikz}
```
Multiple groups: give each `label style={anchor=mid, yshift=..}` so labels align
horizontally. Use `steps=1` to box a single column without swallowing the next gate.

## Wires

Default wire is quantum (solid). Set types globally or mid-circuit:
- Env option: `\begin{quantikz}[wire types={q,c,b,n}]` -- q quantum, c classical, b bundle, n none.
- Mid-circuit: `\setwiretype{q}` (affects this wire from here on; remember it styles the wire
  running *back* to the previous cell, so the change may need to be one column later than expected).
- Single cell only: `\wireoverride{n}` (knocks out one segment without changing the rest).
- Vertical connector: `\wire[d]{q}` (directions u/d/l/r), e.g. to join a control to a distant gate.
- Bundle slash: `\qwbundle{n}` on a single wire instead of three lines.

## Alignment Across Circuits (the fiddly part)

Put the separator literally between the two environments (optionally enlarged with
`\scalebox`), all inside one math context:
```latex
\begin{quantikz}[align equals at=2] ... \end{quantikz}
\scalebox{2}{$=$}
\begin{quantikz}[align equals at=2] ... \end{quantikz}
```

To line up two circuits around an `=`/`$\approx$` between `\end{quantikz}...\begin{quantikz}`:

- Use `align equals at=n` on **each** environment to set which wire sits on the
  baseline (n can be non-integer, e.g. `1.5`). If `wire types` is given, this is
  auto-set to `(N+1)/2`.
- Equalize row spacing with `row sep={0.6cm,between origins}` so every wire is
  evenly spaced (essential when matching multiple circuits).
- If one circuit is "missing" a tall gate on a row, add a `\ghost{X}` of matching
  height to that row to fix vertical drift.
- If gates differ and you can't identify the offender, merge into one circuit with
  no joining wires using `\midstick[n,brackets=none]{=}`.

## Styling

- **Per gate:** `\gate[style={fill=red!20},label style=cyan]{H}`. Common keys:
  `draw=`, `fill=`, `inner xsep=`, `inner ysep=`, `xshift=`, `yshift=`.
  Group multiple values in `{}`.
- **Global:** `\begin{quantikz}[color=blue,background color=yellow]`, plus
  `thin lines` and `transparent` options.
- **By element type** via `\tikzset{ operator/.append style={fill=red!20} }`.
  Style names: `operator`(\gate), `meter`, `slice`, `wave`, `phase`, `group label`
  (\gategroup label), `gg label` (\gate label), `circlewc`(\targ), `crossx2`(\swap,\targX).
  Full table in command-reference.md.
- **Scale a whole circuit:** wrap in `\begin{tikzpicture}\node[scale=1.5]{ ... };\end{tikzpicture}`
  or use `\begin{adjustbox}{width=0.8\textwidth} ... \end{adjustbox}` (needs adjustbox).

## Deeper Reference

- **command-reference.md** -- full catalog of every command and option (environment
  options, `\gate`/`\meter`/`\ctrl`/`\swap`/`\gategroup`/`\slice` parameters,
  `\gateinput`/`\gateoutput`, `\makeebit`, `\trash`/`\ground`, the global-style
  table, defining new gate shapes, and the QCircuit->quantikz2 migration map).
- **tikz-foundations.md** -- the underlying TikZ/PGF concepts quantikz builds on
  (nodes, `name=`/alias, anchors, `fit`, coordinates, styles, scopes,
  `execute at end picture`, layering/`background`) -- needed for overlays, custom
  shapes, and anything beyond the built-in commands.

## Common Mistakes

| Symptom | Cause / Fix |
|---------|-------------|
| "cells not found" / slicing errors | Last row ends in `\\` (remove it), or rows have unequal cell counts (pad with `&`). |
| Stray text where a gate should be | Gate command not first in cell; move `\setwiretype`/`\qwbundle` after it. |
| Last gate has no output wire | Missing trailing `&`. |
| Odd output from `\meter`/`\control` | Missing `{}` after the command. |
| Equals sign sits too high/low | Set `align equals at=` on both circuits; even out `row sep` with `between origins`. |
| Gate widths wrong with `transparent` | Stale `.aux`; delete it and recompile. |
| `\ket` etc. clash with `physics` package | Load quantikz *after* physics; `\forceredefine` at end of preamble to force quantikz's versions. |
| Springer/arXiv rejects tikz | Use tikz `external` library to export each circuit to PDF/image. |

## arXiv note

arXiv's TeX may be too old for quantikz2. Bundle `tikzlibraryquantikz2.code.tex`
(found in your local texmf, or shipped with the package) in your source root.
