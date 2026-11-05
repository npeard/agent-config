# Figures-alone test

A PI's bar for a research report: a casual reader who looks only at the
figures and captions should get the answer to every question the work
asked, and be convinced by what the figures show. If two readers who see
the figures alone cannot, the paper is telling them in prose rather than
showing them.

The orchestrator runs it at step 6 of `writing-orchestration`, once per
draft of the whole document, as four dispatches: Reader 1 twice, Reader
2 twice. Each goes to a fresh subagent on a Sonnet-tier model, as does
the scorer, since Haiku runs disagreed on 4 of 14 questions and
under-reported extras about twofold; none may have written or reviewed
the draft. No reader sees text outside the figures and captions (body,
abstract, intro answers). Caption leads state results, so readers see
them; overclaiming is out of scope.

**Input common to both readers:**

- each figure rendered as the reader will see it, so the built PDF or
  PNG;
- each caption as typeset, in figure order.
  `prose-metrics FILE --captions` prints them in order, with LaTeX
  labels or Typst indices.

If no `QUESTIONS.md` states the questions, stop: the draft has failed
`scientific-writing` section 1, so fix that first.

## 1. Reader 1: evidence quality

**Input.** `QUESTIONS.md` plus the common input. It may read the
plotting code to check what is plotted, but scores the image, since the
reader of the paper sees only the image. Run it twice, on fresh
subagents: one run moved a grade (adequate to weak) with its exhibit
still present, so one read is noise-limited.

**Brief** (paste it as written, then the questions, figures and
captions):

> These are the research questions of a scientific document and its
> figures and captions, and nothing else. For each question: (1) say
> which figures address it and how directly; (2) score the strength of
> their evidence as strong, adequate or weak, and say why: is it
> germane, and is it conclusive? (3) say what each of those figures
> fails to show. Then (4) propose figures to drop, and weak figures to
> merge into stronger ones; a merge may stack tiers as panels on shared
> axes. Do not guess at what a body text might say.

## 2. Reader 2: question inference

**Input.** The common input only, blind to `QUESTIONS.md`, so the
questions it writes come from the figures. Run it twice, on fresh
subagents, since one read's misses are partly noise.

**Brief** (paste it as written, then the figures and captions):

> These are the figures and captions of a scientific document, and
> nothing else. Write the questions these figures answer, one sentence
> each, and name the figures that answer each. Then list anything a
> figure shows that you could not interpret without more text. Do not
> guess at what a body text might say.

## 3. Scoring

`QUESTIONS.md` is frozen for the whole review run, and the reviser never
edits it: scoring against a target the reviser can move measures
nothing.

A fresh subagent scores the matches, given only `QUESTIONS.md` and the
two Reader 2 outputs, since the orchestrator's own judging swung 12, 10
and 14 of 14 on near-identical drafts. Dispatch it once per set of
Reader 2 runs and never again on the same runs, since a second draw is a
chance to pick the better score.

**Brief** (paste it as written, then `QUESTIONS.md` and both runs):

> Below are a list of research questions and two runs of questions a
> reader inferred from figures. For each run, mark each listed question
> matched or missing. A listed question is matched by a run question
> that names the same measured quantity and the same comparison or
> condition; wording and scope breadth do not matter. Each run question
> matches at most one listed question. List every run question that
> matches none as extra. For each match, quote both questions.

A listed question is matched only if both Reader 2 runs match it,
otherwise missing. A question's Reader 1 grade is the higher of its two
runs, so weak means weak in both. Pass: every question matched, none
weak.

| Reader 2 | Reader 1         | Diagnosis                                                | Fix                                                                                  |
| -------- | ---------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| missing  | strong, adequate | question and evidence misaligned                         | fix the figures; report a proposed question change to the owner                      |
| missing  | weak             | presentation failed                                      | fix the weak figure (its (3) list)                                                   |
| matched  | weak             | figure carries the question, evidence weak               | fix the figure (stronger comparison, missing tier, uncertainty), never the question  |
| extra    | any              | a figure serves no question, or `QUESTIONS.md` lacks one | cut the figure as a section 5 candidate, or report the missing question to the owner |

A failure may be fixed by a panel, an annotation or a caption lead that
states the answer. Never fix it in the body, since no reader sees it.
Rerun all four reads and the scorer only after a figure or caption
change, never on an unchanged draft, since that rerun only redraws
noise.

**Never lengthen a caption past `SKILL.md` section 4's budget, or add
caption text the question does not need, to raise a match.** A caption
edit counts only if it states a result the figure shows; a lead that
restates a question's wording to raise a match is the same offence.
Reader 2's uninterpretable list names the captions that need a symbol, a
condition or a method stated.

## 4. Designer step

Pruning cut 57 exhibits to 40, yet results stayed shaped by the
experiment that produced them (ridge and LightGBM kept a table beside
the all-model figure they belong in). So each round, before Reader 1's
candidates are confirmed, redesign by question.

Per question, one fresh designer subagent gets the question and an
inventory of every result available for it: the result keys or files and
which current exhibits show them. It never sees the current figures'
layout, so it is not anchored on them.

**Brief** (paste it as written, then the question and inventory):

> Below is a research question and every result available to answer it.
> Sketch the one primary figure you would draw from scratch to answer
> it: panels, axes, series, and one panel per tier where tiers exist.
> Name the result each series plots. Prior figures are drafts, not
> commitments; that an experiment was run separately, later or by
> another agent is never a reason for a separate exhibit.

The reviser builds that figure. Every existing exhibit for the question
whose data the design contains is folded in and retired; every exhibit
outside it is an ablation candidate and must survive section 5 on its
own. The designed figure enters the ablation as a merge.

## 5. Ablation read

Scoring checks that each question is recovered, never what could go, so
the SMI report reached 57 exhibits with one RMSE in about 17. The
ablation read is the penalty. An exhibit is any figure or table,
labelled or not; each panel counts as one. Appendix exhibits enter every
read, so the appendix holds derivations only. The baseline is the
current round's reads, passing or not: the pass is relative, so it holds
on a failing draft.

1. **Candidates** are the drops and merges proposed by either Reader 1
   run, plus each designed figure and the exhibits it retires.
2. **Confirm.** One group read with every candidate applied: Reader 1
   twice and Reader 2 twice, on the same model tier. If it fails, bisect
   the candidates, non-primary before primary panels, until each failing
   one is isolated, four reads per step; cuts are assumed not to
   interact, and bisection covers the case where they do.
3. **Pass**: both Reader 2 runs keep every prior match, and no
   question's Reader 1 score drops, meaning both runs score it lower
   than the baseline's lower run. A merge passes if it keeps every match
   and no question's Reader 1 grade drops (questions, not figures, are
   scored).
4. **A pass applies the cut**, with no appendix copy, no restating its
   values in the body, and no approval asked: if no reader misses it, it
   was not worth showing. The commit message names the exhibit and the
   questions tested.

A real-versus-synthetic panel that confirms as redundant means the
comparison is badly shown: put the tiers on shared axes, never into a
table.

## 6. Rounds

A round is the designer step, the four reads, the scorer, the ablation,
then fixes: apply ablation-confirmed cuts first, then fix figures, so no
effort goes into an exhibit about to go. Run at most three rounds, then
stop and report the remaining failures, since later rounds chase reader
noise. Every rerun counts toward the three.
