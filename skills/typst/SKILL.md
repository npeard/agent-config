---
name: typst
description: Use when writing, editing or debugging a Typst document (.typ) - covers the traps that compile at exit 0 and render wrong, the LaTeX habits that do not carry over, subequations and numbering, and what to verify before calling a build good.
compatibility: Verified against Typst 0.15.1. Behaviour marked "verified" was executed; behaviour marked "reported" comes from docs or issues and should be re-checked on a different version.
---

# Typst

Typst fails in two modes and only one is loud. An unknown identifier, a
bad modifier, a missing citation key -- hard errors with line numbers,
needing no guidance because the compiler teaches you. The mode that
costs you is the other: **exit 0, no diagnostic, wrong output.**

There is no `--deny-warnings` flag, no linter, and no overflow check
(typst#5759 and typst#6787 both open). So a project needs its own gate,
and "it compiled" is never evidence.

## The silent traps

Each verified by execution on 0.15.1.

### Numbering as a pattern string breaks references

`#set heading(numbering: "S1.1")` compiles, and the *headings* render
`S1` and `S1.1` correctly. References to them silently drop the prefix:
`@h` renders "Section 1", not "Section S1".

```typst
// Wrong -- headings right, references silently lose the "S"
#set heading(numbering: "S1.1")

// Right -- the function applies to the whole counter path
#set heading(numbering: (..n) => "S" + numbering("1.1", ..n))
```

Same for equations and figures, and each counter resets separately --
there is no `\setcounter`:

```typst
#set math.equation(numbering: n => "(S" + str(n) + ")")
#counter(math.equation).update(0)
#show figure.where(kind: image): set figure(numbering: n => "S" + str(n))
#counter(figure.where(kind: image)).update(0)
```

A plain `"1.1"` with no prefix is safe. The trap needs a literal in the
pattern.

### Overflow is not "continues on the next page"

Content that outgrows a fixed-height container **draws outside it and
over whatever follows**, illegibly, at exit 0. Verified: a 1.2em `block`
given three lines of text overprinted the next paragraph.

There is no slide primitive in core Typst -- a theme makes each `=` a
page, so an overlong slide silently becomes two pages, or overlaps.
Fixes, cheapest first:

```typst
// Detect: measure against the container and fail loudly.
#let slide(body) = layout(size => {
  let h = measure(block(width: size.width, body)).height
  assert(h <= size.height, message: "slide overflows: " + repr(h))
  block(breakable: false, height: 1fr, body)
})
```

`panic()`/`assert()` gives a nonzero exit, which is what a build gate
needs given typst#6787. Touying 0.7.1+ detects this itself
(`config-common(breakable: false)`) and also catches *empty* slides, but
only warns -- so it still exits 0. A page-count gate is weakest: it
cannot name the offending slide, and it misses one slide overflowing as
another is deleted.

### `vec()` is a column vector, not an arrow

`$vec(q)$` renders `(q)` -- a one-element matrix in parentheses. No
error. Use `arrow(q)`, and wrap it so muscle memory cannot reach the
wrong one:

```typst
#let vv(x) = math.arrow(x)   // `vv` has no other meaning
```

Reported: the arrow accent sits badly on dotted letters (`i`, `j`) and
replaces the dot. Check the render if you use those.

### References double the noun

Typst prepends "Section"/"Equation"/"Figure" by default, so source that
already writes the word yields "Section Section 1". Verified: `@i`
renders "Section 1"; `@i[Chapter]` renders "Chapter 1".

Converting a LaTeX source whose sites read `Section \ref{...}` means
either editing every site or suppressing globally:

```typst
#set ref(supplement: none)   // then the prose's own word stands
```

## Subequations

Core Typst has no `subequations`. Two options, and pick deliberately:

**`equate`** (reported, v0.3.3) is the closest to standard:

```typst
#import "@preview/equate:0.3.3": equate
#show: equate.with(breakable: true, sub-numbering: true)
#set math.equation(numbering: "(1.1)")
```

Its own README states sub-numbering does not continue across separate
alignment blocks -- each new block takes a new main number. If you need
`(4a)`/`(4b)` on two physically separate equations, that is the
limitation you will hit.

**Hand-rolled**, for that case. A baseline run got this wrong on its
first attempt -- the first equation rendered `(S51)` while the second
rendered `(S51b)` -- and the error was invisible until the rendered text
was read:

```typst
#math.equation(block: true, numbering: n => "(S" + str(n) + "a)", $ ... $) <a>
#math.equation(block: true, numbering: n => "(S" + str(n - 1) + "b)", $ ... $) <b>
#counter(math.equation).update(n => n - 1)   // so the next equation continues
```

Both equations must go through `math.equation` -- leaving the first as a
bare `$ ... $` takes the ambient numbering and produces the asymmetric
pair. The counter reset afterwards is what stops the rest of the
document skipping a number.

**Copy the prefix from the document's own
`#set math.equation(numbering: ...)` line verbatim into both closures.**
Hand-rolled closures do not inherit it: in a document numbering `(S1)`,
writing `"(" + str(n) + "a)"` yields `(50a)` beside `(S50)` everywhere
else -- one equation missing its prefix, at exit 0. A GREEN run of this
skill made exactly that slip while the correct form was on screen, so
the sample is not enough; check the rendered pair against a neighbouring
equation.

**A long `cases()` branch can collide with the equation number.** The
wrapped branch text runs into the tag's column and overprints it --
silent, exit 0, and invisible in the source. Shorten the branch (often
it repeats something already stated on the line above) or check the
render. This is the same class as container overflow below, but it
happens in normal flow with no fixed height anywhere.

## Loud failures: no rule needed

These error with a line number and often a hint. Listed so you recognise
them, not so you avoid them.

| Source                         | Error                                                                                                                             |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `$RMSE$`                       | `unknown variable: RMSE` -- single letters are literals, multiple letters are one identifier. Hint suggests `R M S E` or `"RMSE"` |
| `$dx$`                         | `unknown variable: dx` -- use `d x`, `dif x`, or `"dx"`                                                                           |
| `$angle.l$`                    | `unknown symbol modifier` -- it is `chevron.l` / `chevron.r`. There is no bra/ket builtin                                         |
| `@Missing` with a bibliography | `label does not exist in the document`. **Unlike LaTeX there is no `[?]` marker** -- a bad key fails the build                    |
| `<label>` on plain text        | `cannot reference text` -- labels attach to figures, equations, headings                                                          |

## LaTeX habits that do not carry

Full mapping table in `reference.md`, read on demand. The four that bite
hardest: the LaTeX vector accent is `arrow(q)` and **not** `vec`; angle
brackets are `chevron.l`/`chevron.r`; an align environment becomes one
$...$ block with `&` and a line-break backslash; and there is no
setcounter equivalent -- each counter is updated by name.

## The three modes, and the scoping rule LaTeX authors get wrong

`#` enters code from markup, `$` enters math, `[...]` returns to markup.
In markup, `(1 + 2)` is literal text -- evaluating needs `#(1 + 2)`.
Inside an open code block no further `#` is needed, but a line break
returns to markup, so the next expression needs one again. Inside math,
arguments stay in math unless `#`-prefixed; strings are the exception
and work directly.

**A top-level `#set` applies to the rest of the file**, not to the
current paragraph. This is the opposite of LaTeX's brace-group scoping
and the most common styling surprise:

```typst
#set text(red)        // everything after this is red, to EOF
#[ #set text(blue)    // scoped: blue ends with this block
   blue here ]
```

Attachment grouping uses parentheses, not braces: `x^(2+2)`, not
`x^{2+2}`. A literal comma or semicolon inside a math call is escaped
`\,` / `\;`.

## Paths, fonts, encoding

- **A relative path resolves against the file the call textually lives
  in.** A helper in `lib/theme.typ` written `"build/figures/x.pdf"`
  looks for `lib/build/...`. With `typst compile --root .` run from the
  document's directory, the helper needs a leading `/`:
  `#let figpath(n) = "/build/figures/" + n + ".pdf"`.
- **Font warnings fire once per unresolvable family per build.** List
  only what is installed; speculative fallbacks add noise on the machine
  that builds.
- **`%` and `fr` are not lengths.** `pt/mm/cm/in/em` are `length`; `%`
  is a `ratio` resolved against a container; `fr` is a `fraction` that
  distributes *remaining* space and only means anything inside
  `h`/`v`/`stack`/`grid`. `1fr` as a block height is how you say "the
  rest of the page", which is what makes the overflow assert above work.
- **`block` breaks across pages, `box` does not.**
  `block(breakable: false, ...)` is the constraint that turns a silent
  overflow into something measurable.
- Typst renders ASCII `"` as curly quotes, so an ASCII-only source still
  gets correct typography. An ASCII checker scanning only `.py`/`.md`
  will miss a stray en-dash in a `.typ`.

## Verify the render, not the exit code

Compiling proves the syntax parsed. It says nothing about numbering,
references, or whether anything fits. Before calling a Typst build good:

1. **Zero warnings.** A clean compile prints nothing, so any output is a
   regression. Grep stderr rather than eyeballing.
2. **Read the numbers out of the render.** `pdftotext -layout`, or
   `typst compile --format png --pages N`, then grep for the equation
   and section numbers you expect. This is the only thing that catches
   the numbering and subequation traps.
3. **Grep for doubling** -- `"Section Section"`, `"Equation Equation"`.
4. **Check the page count against the heading count** for a deck, or run
   the overflow assert above.
5. **Pin the compiler.** `typst.toml`'s `compiler` field is a floor, not
   a pin; packages declare no ceiling. Pin the binary in CI (conda-forge
   ships 0.15.1).

Useful flags: `--diagnostic-format short` for machine-readable output,
`--pages 2,3-6` and `--format png --ppi N` to render a subset for
inspection, `--input k=v` to reach `sys.inputs.k`, `--root` for
leading-`/` path resolution. **`typst query` no longer exists on
0.15.1** -- verified absent from the subcommand list; `typst eval` took
over. Code or notes referring to `typst query` predate this.

## Ecosystem

Package and tooling table in `reference.md`. The three that change a
decision: **touying** for slides (not polylux -- 0.4.0 removed themes
and `#pause`), **equate** for subequations, and **no linter exists**.
Bibliography needs no package -- Hayagriva is built in and reads `.bib`.

## Boundaries

`writing-orchestration` owns the prose spine, the review axes and the
ceremony table; this file owns markup and the mechanical half of its
step 5. For a build DAG that fails, use
`superpowers:systematic-debugging` -- that is a bug, not a markup
question. A quantum circuit needs LaTeX/TikZ, so compile it separately
and `image()` the PDF; see the `quantikz` skill.

**Never rewrite prose during a markup conversion.** The port's contract
is that only the markup changed, so `humanizer` does not run on carried
text and a reviewer diffs the two renderings, not the wording.

## Red flags

| Thought                                          | Reality                                                                |
| ------------------------------------------------ | ---------------------------------------------------------------------- |
| "It compiled, so the numbering is right"         | Numbering fails at exit 0. Read the render.                            |
| "Zero warnings means zero problems"              | There is no overflow warning and no warnings-as-errors flag.           |
| "I'll use `numbering: \"S1.1\"`, it looks right" | Headings will. References will silently drop the S.                    |
| "`vec` is the vector one"                        | `vec` is a column matrix. `arrow` is the accent.                       |
| "I'll write `Section @s`"                        | Renders "Section Section 1" unless the supplement is suppressed.       |
| "The first equation can stay a bare `$...$`"     | Then it takes ambient numbering and the pair is asymmetric.            |
| "My sub-numbering closure looks right"           | Does it repeat the document own prefix? A missing S renders at exit 0. |
| "The equation compiled, so it fits"              | A long cases() branch overprints the equation number. Read the render. |
| "A missing citation will show as `[?]`"          | It is a hard error. Not LaTeX.                                         |
| "I'll copy the LaTeX table syntax"               | No `&`, no `\\`, no `\hline`. `table(columns: n, ...)`.                |
| "polylux is the slides package"                  | 0.4.0 removed what you want. Use touying.                              |
