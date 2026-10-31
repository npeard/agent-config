---
name: math
description: Use when deriving, adding, or reviewing an equation in a paper, report, or thesis - covers what a computer can and cannot verify about it, the warrant each step needs, and where a derivation belongs relative to the result that uses it.
compatibility: Symbolic checks assume SymPy; numerical checks assume the project has simulation code the equation can be compared against. Neither is required for a structured derivation.
---

# Math

An equation you did not derive in this session and did not check is a
guess wearing notation. Check what a computer can check, and name the
gaps it cannot.

## What a computer can actually verify

Do not promise total coverage. On a real physics paper -- 21 labeled
equations -- the honest split was roughly: 45% fully machine-checkable,
20% partly, 15% only numerically, and 15-20% not checkable in principle.

| Kind                                                       | Tool                                                      | Notes                                                                                                                                              |
| ---------------------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Algebraic identity, substitution chain, series coefficient | SymPy: `simplify(lhs - rhs) == 0`                         | The clean win. Do these.                                                                                                                           |
| Operator algebra at fixed small size                       | SymPy symbolically at `L = 3, 4`, then numerically larger | General-`L` identities are awkward; do not force them                                                                                              |
| Agreement with simulation                                  | pytest + NumPy against the project's own code             | Highest value per unit effort, because the check usually already exists uncommitted                                                                |
| Asymptotic scaling                                         | SymPy `series`/`limit` on a scalar surrogate              | Confirms the exponent. It does **not** confirm that neglected higher orders are small for the operator norms in play -- that needs a numerical fit |
| Definition                                                 | Nothing                                                   | Nothing to check                                                                                                                                   |
| Modeling assumption, choice of approximation               | Nothing                                                   | No CAS can tell you a truncation was the right one                                                                                                 |

**Do not parse LaTeX into SymPy.** `sympy.parsing.latex` will not
survive a macro-dense source. Transcribe by hand into Python, accept
that the transcription is itself unverified, and have a human read it
once. Pretending the parse is free is how this fails.

**Commit the checks you already ran.** Prose saying "verified
numerically" or "agrees to better than 1e-13" is a check that happened
once and is now unrepeatable. Each such sentence names a check someone
already wrote and threw away. Commit it as a test.

## Introducing an equation

A reader has to know what an equation is for before it can read the
equation. In a review, a PI called out a report that opened with
`y_k(t) = a_k(t)[1 + V_k(t) F(theta_k(t))] - 1 + n_k(t)`: until the
where-list ended, it gave no sign that this was interferometry, that
every channel is its own interferometer, or that `d` moves in time.
Introduce each display in four parts, in this order:

1. **The question.** One or two sentences on what the section needs this
   quantity for, in the reader's words, placed before any symbol
   (`scientific-writing` section 1 owns this framing row).
2. **The familiar case.** If the equation generalizes something the
   reader knows, write that first and say what the general form adds: "A
   Michelson channel reads `cos(4 pi d(t)/lambda + phi)`. Optical
   feedback replaces the cosine with a fringe F that leans, and each
   wavelength is its own channel." Then give the display.
3. **The anchor.** Before the display, one sentence holds both the
   symbol and its name, and says what it buys here. Flag: "how precisely
   a sample fixes d is set by its Fisher information," then the display
   of `J_k(theta)`. Prefer: "The Fisher information J_k of channel k
   bounds how precisely one sample fixes d. We need it because it shows
   which phases leave a channel blind." Defining a symbol in a
   where-list does not anchor it.
4. **The arguments.** A symbol that varies carries its argument at least
   once, as `d(t)` rather than `d`.

**Display a new relation; keep inline math for symbols, short
definitions and values.** The reviewer's example was
`$macron(J) = sum_k E[V_k^2] Phi(C, alpha) (4 pi \/ (lambda_k sigma))^2$`,
placed inline mid-paragraph after the display that used it. It is a
result, so it gets its own numbered line. Inline math is fine for
`sigma`, for `C = 0.2`, or for `(0.635/0.515)^2 = 1.52`. The
`prose-feedback` hook lists inline relations long enough to need a
display. The same list is in `prose-metrics` output.

## Derive once, then refer

Two legitimate structures. Pick one per result and hold it:

- **State the result, defer the derivation.** A paper does this: the
  referee wants the claim and the means to check it, not the algebra
  inline.
- **Derive it where it is used.** A thesis or a tutorial does this.

In a paper the body quotes the closed form and the appendix derives it.
The exception is a derivation that is the paper's main result. Where
that line falls is a judgement.

What is not legitimate is doing both at different rigor levels -- a
hand-waving version in the main text and a careful one in an appendix,
neither pointing at the other. Under a competing pressure ("make this
section self-contained") that is the shape an agent drifts into.

Before adding a derivation, search for it. A measured baseline found the
same derivation already present verbatim in a section about an unrelated
special case, and correctly fixed it by extracting the general part and
leaving a pointer -- but it only found it because it looked.

Symptoms that the structure is wrong:

- A definition the main text depends on lives only in an appendix (an
  axis label defined where the reader arrives after the figure).
- A result is referenced more than once but derived in no single place.
- An equation carries a label nothing references -- either it does not
  need one, or the reference that should exist does not.

## Reason in steps, with each step's warrant

For anything longer than about ten lines, write the derivation as a tree
before writing the prose. Lamport's rules, trimmed to what earns its
place in physics:

1. **Hierarchical step numbers** (1, 1.1, 1.2) -- the numbering is
   scoping, so a later step cannot lean on an assumption no longer in
   force. Cap at 2-3 levels; a physics derivation bottoms out at "this
   is a Fourier transform", not at set theory.
2. **Every step is a statement**, in words, possibly with an equation.
3. **Every step is justified by exactly one of:** obvious or cited;
   named earlier steps ("by 1.2 and 1.3"); or its own children.
4. **A step with neither children nor a justification is an exposed
   gap.** Name it as one. This is the honest form of "I do not know why
   this follows".

`ASSUME`/`CASE`/`QED` bookkeeping is worth it only where an argument
really does split into exhaustive cases. Skip the rest of TLA+.

The tree is a working artifact -- an appendix, a `derivations/` file, or
the branch's notes. It is not the submitted prose; a paper written as a
proof tree is unreadable.

## Boundaries

`writing-orchestration` owns the prose spine and the three review axes;
this skill is the mechanism behind one of them -- Claim integrity's
"every claim traces to a citation, a figure, a derivation, or the
author's own result". Do not restate those axes here.

Lean is not recommended for a physics paper. The load-bearing claims are
about whether a model describes the system, which Lean cannot check;
Mathlib lacks the prerequisites for operator norms on tensor products
plus Magnus expansions plus discrete Fourier analysis, connected; and
the cheap layer -- SymPy, numerical tests, a structured tree -- captures
most of the value at a small fraction of the cost.

## Red flags

| Thought                                                                      | Reality                                                                          |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| "This is a standard result"                                                  | Then cite where. Uncited "standard" is an assumption.                            |
| "I'll parse the LaTeX into SymPy"                                            | Not on a macro-dense source. Transcribe by hand.                                 |
| "The paper says it was checked numerically"                                  | Then the check exists and is uncommitted. Commit it.                             |
| "I'll re-derive it here so the section stands alone"                         | Look for it first. Two rigor levels of one derivation is the defect.             |
| "The scaling is obvious from the exponent"                                   | SymPy confirms the exponent, not that the neglected terms are small.             |
| "I don't quite see why this step follows, but it's right"                    | That is an exposed gap. Label it.                                                |
| (Said "its Fisher information", then displayed J_k without saying J_k is it) | That leaves the reader to guess. One sentence names J_k and says what it is for. |
| "This excerpt already reads as setup" (opens on an equation)                 | Setup comes before the equation. Put the question and the familiar case first.   |
| (Kept the macron(J) closed form inline, after the display that used it)      | If it is a new relation, put it on its own line.                                 |
