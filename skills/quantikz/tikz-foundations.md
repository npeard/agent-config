# TikZ / PGF Foundations for Quantikz

Quantikz is built on TikZ (specifically the `tikzcd`/commutative-diagrams matrix
machinery plus PGF shapes). You only need raw TikZ when going beyond the built-in
commands: overlays, custom shapes, fine positioning, and styling. This file covers
the concepts that show up in that work.

## Mental Model

A `tikzpicture` is a canvas of **coordinates** on which you place **nodes** (boxes
with text/shape) and **paths** (lines, curves). A quantikz circuit is a *matrix of
nodes* -- each cell is a node, wires are paths between node anchors. Most quantikz
keys (`style=`, `label style=`, `inner sep=`, `fill=`, `draw=`) are passed straight
through to the underlying TikZ node.

## Nodes

```latex
\node[draw, fill=white, inner sep=2pt] (myname) at (1,2) {Text};
```
- `draw` outlines, `fill=` colours the interior, `inner sep=` pads text-to-border,
  `outer sep=` pads border-to-anchors, `minimum width/height=` set a floor size.
- `(myname)` names the node so you can refer to it later: `(myname.north)`,
  `(myname.center)`, or draw to it. In quantikz you assign a name via
  `style={alias=myname}` on a gate, because the matrix already owns the node name.
- Text is the `{...}` body; `text width=`, `align=center` control multi-line layout.

## Anchors

Every node exposes anchors: `center`, `north`, `south`, `east`, `west`,
`north east`, etc., plus `text` and shape-specific ones. Reference as
`(node.north)`. Use `anchor=` on a node to choose which of *its* anchors lands on
the given coordinate: `\node[anchor=south] at (p) {...}` places the node's south
edge at `p` (so the node sits *above* `p`). This is the key to precise label
placement (e.g. `label style={anchor=north, yshift=-0.2cm}` in `\gategroup`).

## Coordinates & Positioning

- Absolute: `at (2,3)`. Relative: `at ($(a)+(0,-1)$)` (needs the `calc` library).
- `xshift=`/`yshift=` nudge a node after placement (accept lengths: `0.3cm`, `-2pt`).
- `positioning` library: `right=of a`, `below=1cm of b` for relative layout.
- Lengths: `pt`, `cm`, `mm`, `em`/`ex` (font-relative), and `\textwidth` fractions.

## Styles (tikzset / .style / .append style)

```latex
\tikzset{
  mybox/.style={draw, rounded corners, fill=blue!20, inner sep=4pt},
  operator/.append style={fill=red!20},   % ADD to an existing style, don't replace
}
```
- `name/.style={...}` defines a reusable style; apply with `\node[mybox]`.
- `.append style` extends a style without clobbering its existing keys -- use this
  to tweak quantikz's built-in element styles (`operator`, `meter`, ... see
  command-reference.md) rather than redefining them.
- Colours: `red!20` = 20% red + 80% white; `blue!50!black` = halfway blue/black.
- Common path/box style keys (pass straight through quantikz `style=`):
  `dashed`, `dotted`, `dash dot`, `solid`; `thick`, `very thick`, `thin`,
  `line width=0.8pt`; `rounded corners` (optionally `rounded corners=3pt`);
  `draw=<colour>`, `fill=<colour>`, `opacity=`, `rotate=`. These are TikZ
  primitives, not quantikz-specific -- any TikZ style key works inside `style=`.

## The `fit` Library

```latex
\usetikzlibrary{fit}
\node[draw, fill=white, inner sep=0pt, fit=(a)(b)] (box) {};
```
`fit=(a)(b)` sizes the node to enclose nodes `a` and `b` (and their bounding box).
Common for drawing a frame/overlay around one or more existing gates. Combine with a
second node anchored at `(box.center)` to drop an image or label on top.

## Layering: `background`, `on background layer`, `execute at end picture`

Draw order = paint order; later objects sit on top. Three tools to control this:
- quantikz's `background` key on `\gategroup` draws the highlight *behind* wires.
- `\begin{pgfonlayer}{background}...\end{pgfonlayer}` (with the `backgrounds`
  library) forces content to a back layer regardless of source order.
- `execute at end picture={...}` (a `tikzpicture`/quantikz option) runs TikZ code
  *after* everything else, so it paints on top. This is the standard way to overlay
  a graphic on a gate: place the gate with `style={alias=g}`, then at end-of-picture
  draw a `fit=(g)` box and an `\includegraphics` node at its centre. Scope it to the
  specific environment -- do not use a global `every picture` hook if a document has
  several pictures.

## Scopes

`\begin{scope}[opts] ... \end{scope}` applies `opts` (and clipping/transforms) to a
block without affecting the rest of the picture. `\clip` restricts drawing to a
region. Transforms (`xshift`, `rotate`, `scale`) inside a scope are local.

## Including Graphics

`\includegraphics[options]{file}` (from `graphicx`) drops an external image.
Useful options: `width=`, `height=`, `totalheight=`, `angle=` (rotate),
`scale=`. Inside a node body it becomes the node's content; combine with `fit` +
`execute at end picture` to lay a plot over a gate. `\graphicspath{{dir/}}` sets the
search directory.

## Macros for Repeated Patterns

Use `\newcommand{\name}{...}` to factor out a repeated gate/overlay snippet so the
circuit body stays readable, and `\newcommand{\name}[1]{... #1 ...}` for parameterized
versions. End macro lines with `%` to swallow stray spaces that would otherwise leak
into the circuit matrix.

## Debugging TikZ Positioning

- Temporarily add `draw=red` / `fill=yellow!30` to a node to see its actual extent.
- `\node[draw] at (a.center) {.};` to verify where an anchor really is.
- `show background rectangle` / drawing the bounding box reveals stray whitespace.
- Remember stale `.aux` files cache matrix cell widths -- delete and recompile if
  sizes look wrong after edits (especially with `transparent`).

## Useful Libraries (load via `\usetikzlibrary{...}`)

`fit`, `calc`, `positioning`, `backgrounds`, `shapes.geometric`, `shapes.misc`,
`arrows.meta`, `decorations.pathmorphing` (wavy lines), `external` (export each
picture to its own PDF/image).
