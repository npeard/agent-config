# Quantikz2 Command & Option Reference

Complete catalog distilled from Alastair Kay's quantikz tutorial (v1.x, 2023).
Square brackets `[..]` are optional args; `{..}` mandatory. Labels inside gate
commands are already in math mode; `\lstick`/`\rstick`/`\midstick` labels are in
text mode.

## Environment

`\begin{quantikz}[opts] ... \end{quantikz}` -- comma-separated `opts`:

| Option | Effect |
|--------|--------|
| `wire types={list}` | Per-wire type list from `q` (quantum), `c` (classical), `b` (bundle), `n` (none). Default: all quantum. Setting this auto-sets `align equals at=(N+1)/2`. |
| `thin lines` | Thinner lines (QCircuit-like aesthetic). |
| `transparent` | Transparent background for the whole circuit. |
| `classical gap=` | Separation of the two lines forming a classical wire. Default 0.03cm. |
| `align equals at=n` | Put the vertical centre (baseline, where an external `=` aligns) at wire `n`; `n` may be non-integer. |
| `slice all` | Add an auto-numbered slice after every column. |
| `remove end slices=n` | Suppress the last `n` slices. |
| `slice titles=` | Text for slice labels; use `\col` for the column number. |
| `slice style=` | TikZ style for slice lines (wrap multiple in `{}`). |
| `slice label style=` | TikZ style for slice labels (rotate, space, etc.). |
| `vertical slice labels` | Stack slice label text vertically. |
| `color=` | Border/line colour of gates etc. |
| `background color=` | Cell background colour (pairs well with `\pagecolor`). |
| `column sep=n` / `row sep=n` | Padding between columns/rows. Add `between origins` to measure centre-to-centre instead. |

Also accepts standard `tikzcd`/`tikz` options. Local per-column/row spacing:
`& \gate{X} &[2cm] \gate{H} & \\[1cm]`.

## Gates

`\gate[opts][w][h]{l}` -- box gate. `w`,`h` = optional minimum width/height. `opts`:

| Key | Effect |
|-----|--------|
| `n` (bare integer) | Number of wires the gate spans. Long form `wires=n`. |
| `style=` | TikZ style for the box (`fill=`, `draw=`, `inner xsep=`, ...). |
| `label style=` | TikZ style for the label text. |
| `disable auto height` | Stop each spanned row from inheriting a multi-line label's full height. |
| `swap` | Force a 2-qubit swap depiction. |

`\gateinput[s]{l}`, `\gateoutput[s]{l}` -- put a label inside the current gate on
its input/output edge. Spanning multiple rows groups them with braces (`n`/`wires=n`,
`label style=`, `braces=`). The host `\gate` width does not auto-grow for these --
set its `[w]`.

`\ghost[w][h]{l}` -- invisible gate with the same height as `\gate[][w][h]{l}`.
Must be first in its cell. Used for vertical alignment.

`\phantomgate{s}` / `\hphantomgate{s}` -- a quantum wire occupying the horizontal
(and, for the non-h version, vertical) space of a single-qubit gate labelled `s`.

`\push{t}` -- place text `t` directly on the wire with no box/spacing
(e.g. `\push{\cdots}`, `\push{X}`).

`\linethrough` -- draw a quantum wire across the current cell (sits *under*
multi-qubit gates, so visible only if those gates are transparent). Useful as a
"pass-through" lane.

## Controls, Targets, Swaps

`\ctrl[s]{n}` / `\octrl[s]{n}` -- filled / open control with a vertical wire `n`
rows long (negative allowed). Keys: `style=` (dot + wire), `wire style=` (wire
only, overrides style), `vertical wire=q|c|b`, `open` (`\ctrl[open]{1}` == `\octrl{1}`).

`\control[s]{}` / `\ocontrol[s]{}` -- control dot with no vertical wire (`open` key).

`\targ[s]{}` / `\targX[s]{}` -- CNOT target / swap target (no vertical wire). `style=`.

`\swap[s]{n}` -- X-shape on the current wire plus a vertical wire `n` rows down.
Keys: `partial swap=` (text in a circle for a partial swap), `partial position=`
(fraction along the wire, default 0.5), `style=`, `label style=`, `vertical wire=q|c|b`.

Build arbitrary controlled gates by combining a `\ctrl`/`\control` with a `\gate`
and, where needed, an explicit `\wire[u]{q}`/`\wire[d]{q}` to bridge gaps.

## Measurement

`\meter[opts][w][h]{l}`, `\metercw[opts][w][h]{l}` -- box-style measurements (can
span multiple wires). Keys mirror `\gate`: `n`/`wires=n`, `style=`, `label style=`,
`disable auto height`.

`\measure[s]{l}`, `\measuretab[s]{l}`, `\meterD[s]{l}`, `\inputD[s]{l}` --
single-qubit measurement variants. Note: styling is `[s]` directly (not `[style=s]`).
`\inputD` is the input-side equivalent of `\meterD` and disables the incoming wire.

## Labels & Sticks

`\lstick[s]{t}`, `\midstick[s]{t}`, `\rstick[s]{t}` -- text-mode wire labels at
left/middle/right. Keys: bare integer `n` or `wires=n` (span, adds braces by
default), `label style=`, `brackets=none|left|right|both`, `braces=` (style the braces).

`\verticaltext{l}` -- stack label text vertically (handy in slices / tall gate labels).

`\ket{l}`, `\bra{l}`, `\proj{l}`, `\braket{l}{m}` -- Dirac notation, no math mode
needed, auto-resizing braces. Load quantikz *after* packages like `physics` that
define the same macros; `\forceredefine` (end of preamble) forces quantikz's versions.

## Highlighting & Slicing

`\gategroup[opts]{l}` -- box whose top-left corner sits at the current cell. Keys:
bare integer `n` or `wires=n` (rows covered), `steps=m` (columns covered),
`style=`, `label style=`, `background` (draw behind the circuit -- required if the
box has a fill). Tip: use `label style={anchor=mid, yshift=..}` to align labels
across multiple groups.

`\slice[s]{l}` -- dashed vertical line after the current column, title `l`. Keys:
`style=`, `label style=`. (Or use env options `slice all`, `slice titles=`, etc.)

## Wires (commands)

`\setwiretype[n]{t}` -- set wire `n` (default: current row) to type `q|c|b` from
this column onward. Must come after any gate in the cell.

`\wire[d][n][s]{t}` -- draw a wire from the current cell, type `t` (`a` automatic,
`q`,`c`,`b`), in direction `d` (`u`,`d`,`l`,`r`) for `n` cells, optional style `s`.
After any gate in the cell.

`\wireoverride{t}` -- set just the current cell's incoming wire to type `t`
(including `n` for none) without changing the rest of the row. After any gate.

`\qwbundle[s]{n}` -- render a single wire as a bundle (slash + label `n`). Keys:
`style=`, `Strike Height=`, `Strike Width=`. After any gate.

`\permute{list}` -- wire permutation; `\permute{3,1,2}` connects wire 1->3, 2->1,
3->2 (relative to the command's row). Quantum wires only; overlaps are masked with
the `background color`, so change that if the circuit sits on a non-white backdrop.

`\wave[s]{}` -- draw a wave (the `vdots`/`...` skipped-wires row) across an entire
row; no wire drawn by default -- add `\setwiretype{q}` right after if you want one.

## Termination & Entanglement

`\trash[s]{l}`, `\ground[s]{l}` -- two styles for terminating/tracing-out a wire.
`\makeebit[s]{l}` -- an e-bit: label `l` placed halfway between the current and next
wire, with two lines leading to each. Keys include `angle=` (default -45), `style=`,
`label style=`.

## Global Style Names (for `\tikzset{ NAME/.append style={...} }`)

| Style name | Affects |
|------------|---------|
| `operator` | `\gate` |
| `meter` | `\meter` |
| `slice` | `\slice` |
| `wave` | `\wave` |
| `leftinternal` / `rightinternal` | `\gateinput` / `\gateoutput` |
| `dm` / `dd` | left braces (`\gateoutput`,`\lstick`) / right braces (`\gateinput`,`\rstick`) |
| `phase` | `\phase`, `\control`, `\ophase`, `\ocontrol` |
| `circlewc` | `\targ` |
| `crossx2` | `\swap`, `\targX` |
| `my label` | measurement bases in `\meter` |
| `phase label` | phases in `\phase` |
| `gg label` | main gate label in `\gate` |
| `group label` | label in `\gategroup` |

## Scaling

- `\node[scale=1.5]{ \begin{quantikz}...\end{quantikz} };` inside a `tikzpicture`.
- `\begin{adjustbox}{width=0.8\textwidth} ... \end{adjustbox}` (requires `adjustbox`).

## Externalization

`\usetikzlibrary{external}` then `\tikzexternalize`. Renders each circuit to an
image -- speeds up big documents and satisfies publishers (Springer) that disallow
inline tikz. Circuits inside `amsmath` environments (e.g. `align`) run twice and may
emit duplicate images.

## Defining New Single-Qubit Gate Shapes

quantikz2 lets you base a gate on any TikZ shape. Outline:

1. Pick/define a shape (e.g. from `shapes.geometric`).
2. Add the wire-attachment anchors PGF expects. Quantum wires use the standard
   shape border (works automatically for standard shapes). Classical/bundle wires
   need 8 anchors (+8 aliases): `lstartone`/`lstarttwo`/`lendone`/`lendtwo` (left)
   and `dstartone`/`dstarttwo`/`dendone`/`dendtwo` (down). The `lstartone` anchor
   sits on the left edge 0.03cm above centre; `lstarttwo` 0.03cm below; ends are the
   mirror points on the right edge. Right/up wires are just aliases of left/down via
   `\pgfdeclareanchoralias`.
3. Make a style: `\tikzset{ myshape/.style={thickness, filling, shape=<name>,
   draw=black, inner sep=2pt} }` (`thickness` gets line width right; `filling`
   inherits the background colour).
4. Define the command:
   `\DeclareExpandableDocumentCommand{\mygate}{O{}{m}}{ |[myshape,#1]| {#2} }`.
   Keep the `{m}` argument spec even if you drop the `#2` label.

Multi-qubit version (often visually rough; non-straight edges fight incoming wires):
`\DeclareExpandableDocumentCommand{\mygate}{O{}O{2em}O{1.5em}m}{ \gate[#1,ps=myshape,disable auto height][#2][#3]{#4} }`.

## QCircuit -> Quantikz2 Migration

| QCircuit | Quantikz2 |
|----------|-----------|
| `\QCircuit @C=n @R=m {#}` | `\begin{quantikz}[row sep=m,col sep=n]#\end{quantikz}` |
| `\multigate{n}` | `\gate[n+1]` |
| `\targ` | `\targ{}` |
| `\control` | `\control{}` |
| `\meter` | `\meter{}` |
| `\measureD` | `\meterD{}` |
| `\gategroup{i}{j}{k}{l}{m}` | `\gategroup[k+1-i,steps=l+1-j]` (place in correct cell) |

Quantikz2 vs original quantikz: use `quantikz` not `tikzcd`; `qw`/`cw` no longer
needed (everything has a quantum wire by default); `\meter` labels are now math mode
(error if they start with `$`); `\ctrlbundle` is obsolete (auto-selected); styling
moved from `[s]` to `[style=s]` for most gates; `\targ` now requires `\targ{}`.
