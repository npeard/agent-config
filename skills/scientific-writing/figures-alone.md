# Figures-alone test

A PI's bar for a research report: a casual reader who looks only at the
figures and captions should still understand the results. If a subagent
reading the figures alone cannot explain at least 80% of the results,
the paper is telling them in prose rather than showing them.

**Who runs it.** The orchestrator, at step 6 of `writing-orchestration`,
once per draft of the whole document. The reader is a fresh subagent on
the cheapest model that can read figures. It must not have written or
reviewed the draft.

**Input, and nothing else.** No body text, abstract, title or ledger:

- each figure rendered as the reader will see it, so the built PDF or
  PNG and never the plotting script;
- each caption as typeset, in figure order.
  `prose-metrics FILE --captions` prints them in order, with LaTeX
  labels or Typst indices.

**Brief** (paste it as written, then the figure files and captions):

> These are the figures and captions of a scientific document, and
> nothing else. (1) List every result they establish, one sentence each,
> and name the figure each comes from. (2) Name the document's one to
> three most important results, in one or two sentences each. (3) List
> anything a figure shows that you could not interpret without more
> text. Do not guess at what the body might say.

**Scoring**, done by the orchestrator against the claim ledger:

- every key result the ledger marks appears in answer (2), correct and
  in no more than two sentences;
- at least 80% of the ledger's result rows appear in answer (1). A setup
  or method row is not a result row.

A miss is fixed in the figure or its caption: a panel added, an
annotation, or a lead sentence that states the result. Never fix it in
the body. Run the test again after the fix. Answer (3) lists the
captions that need a symbol, a condition or a method stated.
