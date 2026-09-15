# Typst reference: LaTeX mapping and ecosystem

Lookup tables split out of SKILL.md. The judgement calls stay there;
these are things to check rather than remember.

## LaTeX habits that do not carry

| LaTeX                             | Typst                                                                         |
| --------------------------------- | ----------------------------------------------------------------------------- |
| `\frac{a}{b}`, `\sqrt{x}`         | `frac(a, b)`, `sqrt(x)` -- function calls, no backslash                       |
| `\text{area}`                     | `"area"` -- a quoted string inside math                                       |
| `\vec{q}`                         | `arrow(q)` (**not** `vec`)                                                    |
| `\langle x \rangle`               | `chevron.l x chevron.r`                                                       |
| `\varphi`, `\geq`, `\to`          | `phi.alt`, `gt.eq`, `arrow.r` -- dot modifiers, not distinct names            |
| `\left( \right)`                  | `lr(( ... ))` for auto-sizing                                                 |
| `\begin{align}`                   | one `$ ... $` block, `\` for a break, `&` to align                            |
| `\begin{subequations}`            | no equivalent -- see above                                                    |
| `\label{}` / `\ref{}`             | `<label>` / `@label`, and `@label` is also `\cite`                            |
| `\documentclass`                  | `#show: theme.with(...)` -- no class system                                   |
| `\setcounter`                     | `#counter(x).update(0)`, per counter                                          |
| `\bigstar` as an operator         | `class("binary", star.stroked)` or spacing is wrong                           |
| A bare `i` for the imaginary unit | `upright(i)` -- a bare `i` merges with an adjacent letter into one identifier |

## Ecosystem

Reported, not verified here. Check versions before use.

| Need                              | Package                                                                                                     |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Slides                            | `touying` 0.7.4 (active). **Not** `polylux` -- 0.4.0 removed themes, `#pause` and the fit-to-height helpers |
| Theorems                          | `ctheorems` or `lemmify` -- core has no primitive                                                           |
| Physics notation, braket, tensors | `physica`                                                                                                   |
| Units                             | `metro` (siunitx-like), `unify`                                                                             |
| Plots                             | `lilaq`, or `cetz-plot`                                                                                     |
| Diagrams                          | `cetz` (engine), `fletcher` (nodes and arrows)                                                              |
| Code blocks                       | `codly`                                                                                                     |
| Subequations                      | `equate` -- read the limitation above                                                                       |
| Tables                            | native `table`/`grid`; `tablex` is largely superseded since 0.11                                            |

Bibliography needs no package: Hayagriva is built in, reads `.bib` and
`.yml`, and supports the CSL style repository. Tooling: **tinymist**
(typst-lsp is deprecated), **typstyle** for formatting, no linter yet.
Pandoc has a native Typst writer since 3.1.2, lossy on tables and
citations.
