# Figures-alone test

A PI's bar for a research report: a casual reader who looks only at the
figures and captions should get the answer to every question the work
asked, and be convinced by what the figures show. If two readers who see
the figures alone cannot, the paper is telling them in prose rather than
showing them.

The orchestrator runs it at step 6 of `writing-orchestration`, once per
draft of the whole document, as three dispatches: Reader 1 once, Reader
2 twice. Each goes to a fresh subagent on the cheapest model that can do
it, and none may have written or reviewed the draft. No reader sees the
body, abstract or claimed answers, so the test scores the evidence, not
what the authors say it shows; overclaiming is out of its scope.

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
reader of the paper sees only the image.

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

The orchestrator scores each Reader 2 run against `QUESTIONS.md`. Each
listed question is **matched** if the run wrote a question with the same
subject and quantity, or **missing**; each run question with no listed
match is **extra**. Pass: every question matched in both runs, and no
question scored weak by Reader 1.

| Reader 2 | Reader 1 | Diagnosis                                                | Fix                                 |
| -------- | -------- | -------------------------------------------------------- | ----------------------------------- |
| missing  | strong   | question and evidence misaligned                         | tighten the question                |
| missing  | weak     | presentation failed                                      | redo Reader 1's round               |
| extra    | any      | a figure serves no question, or `QUESTIONS.md` lacks one | cut the figure, or add the question |

A failure is fixed in the figure, the caption or `QUESTIONS.md`: a panel
added or removed, an annotation, or a caption lead that states the
answer. Never fix it in the body, since no reader sees it. Run the
readers again after the fix.

**Never lengthen a caption, or add a caption sentence or annotation, to
raise a match.** A caption carries its lead plus what the answer needs,
and no more, within `SKILL.md` section 4's budget. Reader 2's
uninterpretable list names the captions that need a symbol, a condition
or a method stated.

## 4. Ablation read

Scoring checks that each question is recovered, never what could go, so
the SMI report reached 57 exhibits with one RMSE in about 17. The
ablation read is the penalty. An exhibit is any figure or table,
labelled or not; each panel counts as one. Appendix exhibits enter every
read, so the appendix holds derivations only. Run only on a draft whose
section 3 scoring passes; on a failing draft an ablation measures reader
noise, so fix the figures first.

1. **Candidates** are Reader 1's proposed drops and merges.
2. **Confirm.** One group read with every candidate applied: Reader 1
   once and Reader 2 twice, on the cheapest model that holds accuracy.
   If it fails, bisect the candidates, non-primary before primary
   panels, until each failing one is isolated; cuts are assumed not to
   interact, and bisection covers the case where they do.
3. **Pass**: both Reader 2 runs keep every prior match, and no
   question's Reader 1 score drops. A merge passes if it keeps every
   match and scores no lower than the best figure it replaces.
4. **A pass applies the cut**, with no appendix copy and no approval
   asked: if no reader misses it, it was not worth showing. The commit
   message names the exhibit and the questions tested.

A real-versus-synthetic panel that confirms as redundant means the
comparison is badly shown: put the tiers on shared axes, never into a
table.
