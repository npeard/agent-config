---
name: scientific-writing
description: Use when drafting, revising, or reviewing a scientific paper, talk, or thesis section -- including when paragraphs recite what a figure or equation shows, captions repeat body numbers, a claim recurs across text, captions and appendix, or a revision is called "just a line edit".
compatibility: Before/after measurement uses this repository's `pixi run prose-metrics`. Figure inspection needs the rendered figure, not only its source.
---

# Scientific writing

Each paragraph makes one claim. Its evidence lives in exactly one place
-- a figure, an equation, a table, or prose -- that shows it without
help. Prose explaining visible evidence is repetition; invisible
evidence is a defect in the artifact, not a gap for prose.

Name the genre, then read `genres/<genre>.md` (`paper`, `talk`,
`thesis`): it fixes the reader and where depth goes.

## 1. Claim ledger first

No prose before the section's ledger rows exist. One row per paragraph
(per slide, in a talk):

| Column                    | Content                                  |
| ------------------------- | ---------------------------------------- |
| claim                     | one sentence                             |
| evidence                  | what supports the claim                  |
| medium + location         | Fig. 3b, Eq. (7), Table I, or prose      |
| deferred detail + pointer | what moves elsewhere, and where          |
| transition                | what this claim licenses in the next row |

**Revising starts with a reverse outline.** Write one ledger row per
existing paragraph -- its claim, and where its evidence actually is --
before changing a word. This holds in every ceremony class, Pass
included: a line edit polishes recited evidence, while the outline
exposes it, and a repeated claim shows up as two rows with one claim.

## 2. Evidence routing

Pick the single medium that shows the evidence most directly:

- a trend, comparison or shape -- a figure;
- an exact relation or scaling -- an equation;
- exact values a reader will look up -- a table;
- prose, only when none of those can.

**Inspect the artifact, not its source.** Open the rendered figure, the
typeset equation, the built table, and ask one question: *is the
evidence visible enough that explaining it in prose, in the body or the
caption, would be repetitive?* Matching the prose's numbers to the plot
is not this question.

- **Yes**: the prose states the claim and points to the artifact.
- **No**: change the artifact until the answer is yes. A power law gets
  log axes and a reference slope; a threshold crossing gets labelled
  ticks; a real-versus-imaginary distinction gets colour; a panel that
  shows nothing claimed gets removed; an equation gets rearranged so the
  dependence is explicit.
- **Cannot change it** (no plotting code, out of scope): record the
  change in the medium cell -- "Fig. 2, CHANGE: integer m ticks" -- and
  report it. The prose still states only the claim.

**Sufficiency check.** Delete the artifact: a paragraph still standing
on its own numbers duplicated the evidence. Delete the pointer: the
claim should fall. A claim unsupported even *with* the artifact needs
scoping down or a better artifact.

**Caption and body share a claim, not words.** The caption's lead
sentence states what the figure establishes; the rest carries only what
the plot cannot -- panel key, symbols, conditions, method. Captions
explain "provided they do not repeat information that is being shown in
the figure" (Caltech Hixon Writing Center). The body states the claim in
the argument's terms: what it licenses next, what it qualifies, or where
it breaks. A value the figure shows appears in neither.

**Depth goes behind a pointer** -- extra figures, robustness sweeps, a
derivation that would interrupt the arc between adjacent claims. A
load-bearing claim never lives only in an appendix. Derivation placement
is `math`'s "Derive once, then refer".

## 3. Paragraphs and sentences

The topic sentence is the claim; setup and procedure follow it. One
claim per paragraph -- a second argument starts a second paragraph.

From Strunk 1918, with its rule numbers:

- **8, 9**: the paragraph is the unit; it opens with its topic sentence.
- **10**: active voice when the actor matters; passive when the object
  is the topic.
- **11**: positive form, except a real negative result.
- **12, 13**: concrete language; omit needless words.
- **15, 16, 18**: parallel form; related words together; emphasis at the
  end.

Part I usage rules and the White-era additions are excluded on purpose
-- contested or copyrighted.

## 4. Numeric budgets

Defaults; a genre file may override them:

- paragraph: at most 5 sentences or about 120 words;
- caption beyond its panel key: at most 3 sentences;
- section: a word budget, set atop the ledger.

`pixi run prose-metrics <file> [--json]` reports these sizes plus
`shared_numerics`, numbers in both a caption and the body. It does not
gate.

## 5. Precision

- **A term of art is not jargon.** Write "propagator", not "the forward
  trajectory of all basis states"; "k = 0, pi", not "the two
  self-conjugate ones". A paraphrase needs a gloss the term did not.
- **One name per quantity.** Synonym churn ("spinon", "localized
  excitation", "the defect") reads as several objects.
- **A coined term needs a reason in the ledger**: every use costs the
  reader a definition.
- **Fix an overclaim by scoping it**, with a pointer: "is insensitive to
  the choice of target (Fig. 2)". Never by reciting more of the plot.
- **Hedge only where uncertainty is real**, and name it.
- **Never set up a fact to retract it.** State what holds.

## 6. Review checks

Reviewers run these per section:

- **Skim test**: the topic sentences alone reconstruct the argument.
- **Removal test**: the sufficiency check, per paragraph.
- **Repetition audit**: each claim stated once in the body; a caption
  restates it only as its lead sentence.
- **Fresh expert reader**: a subagent given the genre's reader, and only
  the rendered text and figures, says what each section established and
  lists every sentence it would skip.
- **`prose-metrics`** before and after, delta reported. Each shared
  numeric needs a reason the figure cannot show the value.

## 7. Red flags

Quoted from the no-skill baseline.

| Thought                                                                                                                                  | Reality                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| "I classified this as a Pass: line edits and claim fixes, with the argument unchanged."                                                  | The reverse outline runs in every class.                                                          |
| "It also says the OBC 90th percentile is below 10^-3 at m >= 5, which I read off the band"                                               | Reciting the plot is not a fix. Scope the claim; point to the figure.                             |
| "The figure shows OBC about 20-30x above PBC, with the same slope. The old text never mentioned this, so I added a sentence stating it." | Shown by the figure, so not said in prose. If it matters and is not obvious, annotate the figure. |
| "adds a sentence covering panels F and G, and states the C_YZ exception."                                                                | A contradicting panel means the claim is scoped wrong. Narration hides it.                        |
| (Opened the figure only to check the prose's numbers)                                                                                    | Ask the visibility question instead.                                                              |
| "that bond is \\emph{imaginary}"                                                                                                         | Colour real against imaginary in the figure.                                                      |
