---
name: scientific-writing
description: Use when drafting, revising, or reviewing a scientific paper, talk, or thesis section -- including when paragraphs recite what a figure or equation shows, captions repeat body numbers, a claim recurs across text, captions and appendix, or a revision is called "just a line edit".
compatibility: Before/after measurement comes from the `prose-feedback` hook, or `prose-metrics` without it (section 4). Figure inspection needs the rendered figure, not only its source.
---

# Scientific writing

Each paragraph makes one claim. Its evidence lives in exactly one place
-- a figure, an equation, a table, or prose -- that shows it without
help. Prose explaining visible evidence is repetition. Invisible
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

**Updating a number starts with whether it belongs.** Before changing a
value in prose, ask whether the figure shows it. If it does, cut it.

**Depth goes behind a pointer** -- extra figures, robustness sweeps, a
derivation that would interrupt the arc between adjacent claims. A
load-bearing claim never lives only in an appendix. Derivation placement
is `math`'s "Derive once, then refer".

## 3. Paragraphs and sentences

**Do not answer an objection the reader has not raised.** A sentence
defending a choice nobody questioned is the tell. Cut it.

**Every reference points backward.** The reader reads in order. Only a
float, or an appendix named from the main body, may be named before it
appears: an appendix pointing to a later appendix is a forward
reference. Plain words count: "as we show below" and "Sec. V will" are
forward references.

**Revising cuts sentences before it shortens them.** A measured author
rewrite, at a median of 21 words a sentence, kept one sentence for every
three it removed. A sentence the request did not ask for needs a reason.
A revision not asked to add content is finished only when the hook's
sentence count has fallen; if it rose, drop clauses rather than split
them and cut again before reporting.

Style:

- one independent clause per sentence. Drop the clause after `;`, `:` or
  `---` first, and split only when both halves carry a claim the
  paragraph needs;
- purpose in the first person: "We seek the program of minimum S among
  all nonnegative dwell times...";
- a sentence over 30 words: drop a clause first.

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

## 4. Numeric budgets

Defaults a genre file may override:

- paragraph: at most 5 sentences or about 120 words;
- caption beyond its panel key: at most 3 sentences;
- section: a word budget, set atop the ledger.

The `prose-feedback` hook reports after every edit to a `.tex` or `.typ`
file. It gives sentence count, median and 90th-percentile words, and
chained-clause rate, each against the file's first report. On a revision
the sentence count should fall. A forward reference it lists is a
defect, not a style choice.

Without the hook, run
`pixi run --manifest-path ~/.agents/agent-config/pixi.toml prose-metrics ABSOLUTE_FILE [--json]`.
It also reports `shared_numerics`, numbers in both a caption and the
body. It does not gate.

## 5. Precision

- **A term of art is not jargon.** Write "propagator", not "the forward
  trajectory of all basis states"; "k = 0, pi", not "the two
  self-conjugate ones". A paraphrase needs a gloss the term did not.
- **One name per quantity.** Synonym churn ("spinon", "localized
  excitation", "the defect") reads as several objects.
- **A coined term needs a reason in the ledger**: every use costs the
  reader a definition.
- **Claim-first never strengthens a claim** beyond what the pointed
  artifact shows. A question the original posed stays one until it does.
- **Fix an overclaim by scoping it**, with a pointer: "is insensitive to
  the choice of target (Fig. 2)". Never by reciting more of the plot.
- **Hedge only where uncertainty is real**, and name it.
- **Every reported statistic names its split**: training, validation or
  test. A number with no split is a defect.

## 6. Review checks

Per section:

- **Skim test**: the topic sentences alone reconstruct the argument.
- **Removal test**: section 2's sufficiency check, per paragraph.
- **Repetition audit**: section 2's caption-and-body rule, per claim.
- **Fresh expert reader**: a subagent playing the genre's reader, given
  only the rendered text and figures, says what each section established
  and which sentences it would skip.
- **`prose-metrics` shared numerics**: each needs a reason the figure
  cannot show the value.

## 7. Red flags

Quoted from agent runs, and from agent sentences an author cut.

| Thought                                                                                                                                                               | Reality                                                                                           |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| "I classified this as a Pass: line edits and claim fixes, with the argument unchanged."                                                                               | The reverse outline runs in every class.                                                          |
| "It also says the OBC 90th percentile is below 10^-3 at m >= 5, which I read off the band"                                                                            | Reciting the plot is not a fix. Scope the claim; point to the figure.                             |
| "The figure shows OBC about 20-30x above PBC, with the same slope. The old text never mentioned this, so I added a sentence stating it."                              | Shown by the figure, so not said in prose. If it matters and is not obvious, annotate the figure. |
| "adds a sentence covering panels F and G, and states the C_YZ exception."                                                                                             | A contradicting panel means the claim is scoped wrong. Narration hides it.                        |
| (Opened the figure only to check the prose's numbers)                                                                                                                 | Ask the visibility question instead.                                                              |
| "...and the engineered program transports it as the target does"                                                                                                      | Panel H shows it 1.5-2 sites off; the original asked whether.                                     |
| "which makes it the hardest target here"                                                                                                                              | A ranking with no ledger row or evidence.                                                         |
| (A revision that splits long sentences and removes none)                                                                                                              | Revising cuts sentences first. The count should fall.                                             |
| "to a mean absolute error of $0.43$ sites against $0.45$"                                                                                                             | The figure shows it. Cut it, do not update it.                                                    |
| "This is a choice of presentation rather than of physics."; "the obstruction is exact rather than a matter of degree"; "this is a design error and not Trotter error" | An answer to an objection nobody raised. Cut it.                                                  |
| "We use it as a test of sign structure rather than as a model of a one-dimensional metal" (added by a revision run)                                                   | A new sentence needs a reason the request gave. This one has none.                                |
| "The three examples thus differ in what reduction gives up."                                                                                                          | A synthesis no ledger row asked for. Each example already made its claim.                         |
| "warm-starting each step from the previous solution"; "a bound-constrained quasi-Newton solver (L-BFGS-B) suffices" (added by a revision run)                         | Solver internals. State the problem, not how it was solved.                                       |
| "The number of points in the Brillouin zone --- and hence the number of pulses per Floquet cycle --- is at most $2^d$ times larger..."                                | Two clauses and an aside. Give each its own sentence, or drop it.                                 |
| `This example and the RKKY model of Sec.~\ref{sec:rkky} are complementary` (before that section)                                                                      | A forward reference. Point backward, or cut it.                                                   |
| (Filled an empty `\cite{}` with a key of its own choosing)                                                                                                            | Not asked for. An empty citation is the author's to fill.                                         |
