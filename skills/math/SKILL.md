---
name: math
description: Use when deriving, adding, or reviewing an equation in a paper, report, or thesis - covers stating where each step came from, what a computer can and cannot verify about it, and where a derivation belongs relative to the result that uses it.
compatibility: Symbolic checks assume SymPy; numerical checks assume the project has simulation code the equation can be compared against. Neither is required to state provenance.
---

# Math

An equation you did not derive in this session and did not check is a
guess wearing notation. Say which it is, in the artifact, before anyone
asks.

## State provenance unprompted

Every equation you add gets one of four statuses, recorded where the
work lives -- a register file, a comment beside the test, or the commit
message. Not in the rendered prose, which is for the reader.

| Status       | Means                                                 | Obligation                                       |
| ------------ | ----------------------------------------------------- | ------------------------------------------------ |
| `derived`    | You did the algebra, this session or in a cited place | A committed symbolic or by-hand check            |
| `numerical`  | It agrees with code that computes the same thing      | A committed test naming the tolerance            |
| `definition` | It defines a symbol; there is nothing to check        | Say so explicitly                                |
| `assumption` | An approximation or model choice                      | Its validity condition, and where that is tested |

**An unclassified equation is the defect.** This is the register's whole
value: not that every equation is verified -- most cannot be -- but that
none is silently unexamined.

The failure this exists to stop, from a measured baseline: an agent
added three equations to a physics paper and, asked afterwards how it
knew each was correct, answered *"I did not re-derive BCH from
scratch"*, *"I did not re-verify this manipulation from first
principles, I trusted the paper's prior derivation"*, and *"I did not
re-derive this fidelity formula; I am asserting it is standard"*. All
three were defensible. None was stated until asked, and the prose read
as a confident derivation.

**"Standard result" is a status, not an exemption.** If a step is
standard, cite where it is standard. An uncited "standard" step in a
paper's central claim is an `assumption` whose validity condition is
"the literature agrees", and a reader cannot check that without the
reference.

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
| Definition                                                 | Nothing                                                   | Say `definition` and stop                                                                                                                          |
| Modeling assumption, choice of approximation               | Nothing                                                   | No CAS can tell you a truncation was the right one                                                                                                 |

**Do not parse LaTeX into SymPy.** `sympy.parsing.latex` will not
survive a macro-dense source. Transcribe by hand into Python, accept
that the transcription is itself unverified, and have a human read it
once. Pretending the parse is free is how this fails.

**Commit the checks you already ran.** Prose saying "verified
numerically" or "agrees to better than 1e-13" is a check that happened
once and is now unrepeatable. Those sentences are the cheapest possible
starting set: each names a check someone already wrote and threw away.

A hand-maintained register rots. Measured on the same paper: one
registered equation no longer existed in the source, 11 of 21 were
unregistered including the central result, and a recorded value
contradicted the paper. If a register is worth keeping, a script must
check that every label has an entry, every entry has a label, and every
`derived`/`numerical` entry names a test that exists.

## Derive once, then refer

Two legitimate structures. Pick one per result and hold it:

- **State the result, defer the derivation.** A paper does this: the
  referee wants the claim and the means to check it, not the algebra
  inline.
- **Derive it where it is used.** A thesis or a tutorial does this.

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
   this follows", and it is the same defect as an unclassified equation
   one level down.

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
the cheap layer -- provenance, SymPy, a structured tree -- captures most
of the value at a small fraction of the cost.

## Red flags

| Thought                                                   | Reality                                                              |
| --------------------------------------------------------- | -------------------------------------------------------------------- |
| "This is a standard result"                               | Then cite where. Uncited "standard" is an assumption.                |
| "I'll trust the paper's earlier derivation"               | Fine -- and say so, in the artifact, unprompted.                     |
| "Every equation should be verified"                       | Most cannot be. Classify all of them; verify what is verifiable.     |
| "I'll parse the LaTeX into SymPy"                         | Not on a macro-dense source. Transcribe by hand.                     |
| "The paper says it was checked numerically"               | Then the check exists and is uncommitted. Commit it.                 |
| "I'll re-derive it here so the section stands alone"      | Look for it first. Two rigor levels of one derivation is the defect. |
| "The scaling is obvious from the exponent"                | SymPy confirms the exponent, not that the neglected terms are small. |
| "I don't quite see why this step follows, but it's right" | That is an exposed gap. Label it.                                    |
