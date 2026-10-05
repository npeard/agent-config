---
name: scientific-writing
description: Use when drafting, revising, or reviewing a scientific paper, talk, or thesis section -- including when paragraphs recite what a figure or equation shows, captions repeat body numbers, a claim recurs across text, captions and appendix, or a revision is called "just a line edit".
compatibility: Before/after measurement uses `prose-metrics` (section 4). Figure inspection needs the rendered figure, not only its source.
---

# Scientific writing

Each paragraph makes one claim. Its evidence lives in exactly one place
-- a figure, an equation, a table, or prose -- that shows it without
help. Prose explaining visible evidence is repetition; invisible
evidence is a defect in the artifact, not a gap for prose.

Name the genre, then read `genres/<genre>.md` (`paper`, `talk`,
`thesis`): it fixes the reader and where depth goes.

## 1. Claim ledger first

No prose before the section's ledger rows exist. One row per paragraph:
**claim** (one sentence); **evidence**; **medium + location** (Fig. 3b,
Eq. (7), Table I, or prose); **deferred detail + pointer** (what moves
where); **transition** (what the claim licenses in the next row).

**Revising starts with a reverse outline**, in every ceremony class,
Pass included: one row per existing paragraph -- its claim, and where
its evidence actually is -- before changing a word. It exposes what a
line edit polishes: recited evidence, and a repeated claim as two rows.
Each row ends kept, moved (where), or cut for a reason: redundant,
textbook for the genre's reader, or contradicted by the artifact. Moving
evidence to a figure never cuts the claim it supports.

A summary, ranking or comparison is a claim: own row, own evidence.

## 2. Evidence routing

Pick the one medium that shows the evidence most directly:

- a trend, comparison or shape -- a figure;
- an exact relation or scaling -- an equation;
- exact values a reader will look up -- a table;
- prose, only when none of those can.

**Inspect the rendered artifact, not its source**, and ask: *is the
evidence visible enough that explaining it in prose, in the body or the
caption, would be repetitive?* Matching the prose's numbers to the plot
is not this question. Read the pointed panel itself: a pointer to a
panel that does not show the claim is a claim-integrity error.

- **Yes**: the prose states the claim and points to the artifact.
- **No**: change the artifact until the answer is yes -- log axes and a
  reference slope for a power law, labelled ticks for a threshold,
  colour for real versus imaginary, a panel removed, an equation
  rearranged so the dependence is explicit.
- **Cannot change it** (no plotting code, out of scope): record the
  change in the medium cell -- "Fig. 2, CHANGE: integer m ticks" -- and
  report it. The prose still states only the claim.

**Sufficiency check.** Delete the artifact: a paragraph still standing
on its own numbers duplicated the evidence. Delete the pointer: the
claim should fall. A claim unsupported even *with* the artifact needs
scoping down or a better artifact.

**Caption and body share a claim, not words.** The caption's lead
sentence states what the figure establishes; the rest carries only what
the plot cannot -- panel key, symbols, conditions, method. The body
states the claim in the argument's terms: what it licenses next, what it
qualifies, or where it breaks. A value the figure shows appears in
neither.

**Depth goes behind a pointer** -- extra figures, robustness sweeps, a
derivation that would interrupt the arc between adjacent claims. A
load-bearing claim never lives only in an appendix. Derivation placement
is `math`'s "Derive once, then refer".

## 3. Paragraphs and sentences

The topic sentence is the claim; setup and procedure follow it. One
claim per paragraph.

From Strunk 1918, with its rule numbers:

- **8, 9**: the paragraph is the unit; it opens with its topic sentence.
- **10**: active voice when the actor matters; passive when the object
  is the topic.
- **11**: positive form, except a real negative result.
- **12, 13**: concrete language; omit needless words.
- **15, 16, 18**: parallel form; related words together; emphasis at the
  end.

Part I and White-era rules are excluded: contested or copyrighted.

## 4. Numeric budgets

Defaults a genre file may override:

- paragraph: at most 5 sentences or about 120 words;
- caption beyond its panel key: at most 3 sentences;
- section: a word budget, set atop the ledger.

`pixi run --manifest-path ~/.agents/agent-config/pixi.toml prose-metrics ABSOLUTE_FILE [--json]`
reports these sizes plus `shared_numerics`, numbers in both a caption
and the body. It does not gate.

## 5. Precision

- **A term of art is not jargon.** Write "propagator", not "the forward
  trajectory of all basis states"; "k = 0, pi", not "the two
  self-conjugate ones". A paraphrase needs a gloss the term did not.
- **One name per quantity.** Synonym churn ("spinon", "localized
  excitation", "the defect") reads as several objects.
- **A coined term needs a reason in the ledger**: every use costs the
  reader a definition.
- **Claim-first never strengthens a claim** beyond what the pointed
  artifact shows; a question the original posed stays one until it does.
- **Fix an overclaim by scoping it**, with a pointer: "is insensitive to
  the choice of target (Fig. 2)". Never by reciting more of the plot.
- **Hedge only where uncertainty is real**, and name it.

## 6. Review checks

Per section:

- **Skim test**: the topic sentences alone reconstruct the argument.
- **Removal test**: section 2's sufficiency check, per paragraph.
- **Repetition audit**: section 2's caption-and-body rule, per claim.
- **Fresh expert reader**: a subagent playing the genre's reader, given
  only the rendered text and figures, says what each section established
  and which sentences it would skip.
- **`prose-metrics`** before and after, delta reported. Each shared
  numeric needs a reason the figure cannot show the value.

## 7. Red flags

Quoted from no-skill and skill runs.

| Thought                                                                                                                                  | Reality                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| "I classified this as a Pass: line edits and claim fixes, with the argument unchanged."                                                  | The reverse outline runs in every class.                                                          |
| "It also says the OBC 90th percentile is below 10^-3 at m >= 5, which I read off the band"                                               | Reciting the plot is not a fix. Scope the claim; point to the figure.                             |
| "The figure shows OBC about 20-30x above PBC, with the same slope. The old text never mentioned this, so I added a sentence stating it." | Shown by the figure, so not said in prose. If it matters and is not obvious, annotate the figure. |
| "adds a sentence covering panels F and G, and states the C_YZ exception."                                                                | A contradicting panel means the claim is scoped wrong. Narration hides it.                        |
| (Opened the figure only to check the prose's numbers)                                                                                    | Ask the visibility question instead.                                                              |
| "...and the engineered program transports it as the target does"                                                                         | Panel H shows it 1.5-2 sites off; the original asked whether.                                     |
| "which makes it the hardest target here"                                                                                                 | A ranking with no ledger row or evidence.                                                         |
