# Figures-alone test

A PI's bar for a research report: a casual reader who looks only at the
figures and captions should still get the answer to every question the
work asked, and be convinced by what the figures show. If a subagent
reading the figures alone cannot, the paper is telling them in prose
rather than showing them.

The orchestrator runs it at step 6 of `writing-orchestration`, once per
draft of the whole document, in two dispatches: first the ledger, then
the figures-only read. Each goes to a fresh subagent on the cheapest
model that can do it, and neither may have written or reviewed the
draft. The reader never sees the ledger, and the ledger is never built
from the reader's answer.

## 1. The ledger: one answer per question

A ledger that lists every distinct result fails the test by
construction. The same PI asked fewer than five questions of one report;
a builder told to list "every distinct result" returned 56 flat rows,
one per sentence with a number, guard or reviewer caveat. With 19 of
them prose-only, the report failed by construction. The PI asked for as
many results as questions, with the rest reclassified as support.

**Input.** The questions the work set out to answer, quoted from the
brief or spec, or from the introduction if neither exists, and the
draft's full text. If no source states the questions, stop: the draft
has failed `scientific-writing` section 1, so fix that first.

**Brief** (paste it as written, then the questions and the draft):

> Build the claim ledger for this document, in four parts. (1)
> Questions: list the questions given, quoted. (2) Answers: one per
> question, one or two sentences each, naming the figure that carries
> it. There are exactly as many answers as questions. (3) Support: every
> other result in the draft goes under the answer it supports, as one of
> two kinds. An **evidence** row is a value, trend or comparison the
> answer rests on, which a figure can show. A **derivation or caveat**
> row is a derivation, a bound's role, a mechanism, a caveat, or a
> diagnosis of a failed run. (4) Unscored: method, setup and context
> rows, and every pre-registered prediction.

## 2. The figures-only read

**Input, and nothing else.** No body text, abstract, title or ledger:

- each figure rendered as the reader will see it, so the built PDF or
  PNG and never the plotting script;
- each caption as typeset, in figure order.
  `prose-metrics FILE --captions` prints them in order, with LaTeX
  labels or Typst indices.

**Brief** (paste it as written, then the figure files and captions):

> These are the figures and captions of a scientific document, and
> nothing else. (1) List every result they establish, one sentence each,
> and name the figure each comes from. (2) Name the few results the
> document exists to report, in one or two sentences each. For each, say
> whether its figure's evidence convinces you, and why: is it germane,
> and is it conclusive? Then name anything shown that is beside the
> point or more than the result needs. (3) List anything a figure shows
> that you could not interpret without more text. Do not guess at what
> the body might say.

## 3. Scoring

The orchestrator scores the read against the ledger. Pass rests on the
answers alone. Every answer must appear in read (2), correct and in no
more than two sentences, and the reader must judge its figure's evidence
germane and conclusive. A read that records no such judgment has not
passed.

Evidence-row coverage is advisory: report the share of evidence rows in
read (1), with the value read off the plot or stated in a caption, but
never pass or fail on it. Derivation, caveat, method and prediction rows
are not counted.

A failed answer is fixed in its figure or caption: a panel added or
removed, an annotation, or a caption lead that states the answer. Never
fix it in the body. The evidence rows under that answer say what the
reader lacked. Run the read again after the fix.

**Never lengthen a caption, or add a caption sentence or annotation, to
raise coverage or recall.** A caption carries its lead plus what the
answer needs, and no more, within `SKILL.md` section 4's budget. Cut
what read (2) calls beside the point or more than needed. Read (3) lists
the captions that need a symbol, a condition or a method stated.
