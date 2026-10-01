---
name: writing-orchestration
description: Use when orchestrating a prose deliverable end to end -- a paper, thesis chapter, talk, or long-form documentation -- where no test can assert the result is correct. Carries what each spine step means for writing, the review axes a reader must judge, and how much ceremony the work needs.
compatibility: Requires workflow-orchestration and currently expects the Superpowers skill set plus host support for subagents and independent review.
---

# Writing Orchestration

<SUBAGENT-STOP>
If you were dispatched to draft one section, or to review one section, stop
here and do that. This file is the orchestrator's contract -- classification,
substitutions, and the review axes -- and none of it applies to writing a
single section. Reading it costs you context and changes nothing about your
job.
</SUBAGENT-STOP>

The numbered spine lives in the master `AGENTS.md`, and it does not
change here. This skill carries what each step *means* when the
deliverable is prose, and the gate policy in `workflow-orchestration`
applies unchanged.

**The boundary.** `workflow-orchestration` owns deliverables whose
correctness a test asserts. This skill owns deliverables whose
correctness a reader judges. Everything below follows from that one
difference: with no test, verification splits into a mechanical half --
it builds, the references resolve, it fits the page limit -- and a
judged half, and the judged half needs a reviewer rather than a command.

## Classification picks the spine, not the toolbox

Choosing this skill does not put the coding skills out of reach:

- A LaTeX build that fails is a bug. Use
  `superpowers:systematic-debugging`, exactly as for code.
- Three sections with no shared prose are independent work. Use
  `superpowers:dispatching-parallel-agents`.
- Claiming a chapter is finished needs
  `superpowers:verification-before-completion`, unchanged.
- A docstring or README that reads like a chatbot wrote it needs
  `humanizer`, even though the project is code.

**Invoke a skill by the pattern you are fixing, not by the file
extension.** A prose deliverable does not make the coding skills wrong,
and a code repository does not make the writing skills wrong.

## Ceremony scales

| Class    | Meaning                                                                  | Sequence                                                |
| -------- | ------------------------------------------------------------------------ | ------------------------------------------------------- |
| Pass     | Line edits to prose that already exists; the argument is not in question | Reverse outline, edit, then report what changed and why |
| Section  | A new subsection into a document whose argument already exists           | Ledger rows in chat, get a nod, draft                   |
| Document | A new chapter or paper, or a restructure that changes the argument       | The full spine                                          |

For a scientific genre the class sets the gates and the spec, not
whether the `scientific-writing` ledger exists.

When torn between two classes, take the heavier one. Discovering that a
"pass" is actually rewriting the argument upgrades the class: stop, say
so, re-classify. Nothing downgrades mid-task.

## What each step means

| Step         | For code                                         | For prose                                                                                                                                                                                                                                                                         |
| ------------ | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0 Preflight  | Tests green, clean tree, default branch          | The document builds today, clean tree, default branch. A build already broken hides what you break next                                                                                                                                                                           |
| 1 Understand | A quantifiable success metric                    | The claim, the genre and the specific reader, the venue's page or word limit, and what that reader must believe by the end. Take the `scientific-writing` section 4 baseline; step 5 reports the delta against it. Documentation: name the reader, what they know, what to define |
| 2 Specify    | Interfaces and the tests that fix them           | The claim ledger from `scientific-writing`, with a word budget per section                                                                                                                                                                                                        |
| 3 Isolate    | Feature branch; worktree when phases parallelise | Unchanged                                                                                                                                                                                                                                                                         |
| 4 Implement  | A subagent per phase, a fresh reviewer per phase | A draft per section; every brief names `scientific-writing` and the genre. The drafter reports artifact changes made or needed (`scientific-writing` section 2); the reviewer reads that section and the ledger                                                                   |
| 5 Verify     | Run the command, read the output                 | Builds clean, every reference and citation resolves, inside the page budget -- see below for Typst; report the `prose-metrics` delta from step 1                                                                                                                                  |
| 6 Review     | code-review, then standards-and-spec-review      | The four axes below, then `humanizer` last as a lint, then re-verify the build                                                                                                                                                                                                    |
| 7 Integrate  | PR or merge, then reflect                        | Unchanged                                                                                                                                                                                                                                                                         |

**A revision replaces the claim it revises.** When a phase overturns an
earlier conclusion, the spec says *replace claim X with Y* -- never *add
a retraction of X*. This is the orchestrator's rule because it is the
brief that causes the defect: an agent told to "retract the 9-38% claim"
correctly produces a retraction slide, and the reader of that deck never
held the claim. The superseded version belongs in the commit message and
the chat. `CODING_STANDARDS.md` rule 11 carries the author-facing half.

**Typst fails quietly where LaTeX fails loudly**, so step 5 needs a
different bar. An undefined LaTeX `\ref` is a warning you can grep; an
unresolved Typst citation renders as a visible marker and still exits 0,
and content that outgrows a page just continues onto the next one with
no diagnostic at all. There is no `chktex` equivalent and no
warnings-as-errors flag. So a Typst project needs a build gate rather
than an eyeball -- a page-count or overflow check the build runs -- and
"it compiled" is not evidence. Where a project has that gate, trust it
and say what it reported; where it does not, that gate is the first
thing to add. Copy the document's existing conventions (table idiom,
ASCII rule) rather than deriving markup from LaTeX habits.

**A markup conversion is a distinct task shape.** Porting a document
between markup languages -- LaTeX to Typst, Markdown to LaTeX -- is not
drafting. Its contract is that only the markup changed, so the review
axes below do not apply to text carried across, and `humanizer` must not
run on it. Verify a conversion by diffing the two *renderings*, not by
re-judging the prose. Newly drafted sections inside a converted document
are ordinary prose and take the full step 6.

## The four review axes

`code-review` has no prose equivalent, so these replace it at step 6.

**Claim integrity.** Every claim traces to a citation, a figure, a
derivation, or the author's own result. This is the axis with no code
analogue and the one most expensive to catch late: a fabricated
reference or a number appearing nowhere in the data passes every
mechanical check, reaches a reader, and costs credibility rather than a
build. Never invent a number, citation, reference, or attribution. When
a sentence needs a fact you do not have, ask for it or write the weaker
sentence you can support.

**Notation consistency.** One symbol per quantity across the whole
document, matching the project's notation file where it has one. This
drifts silently because every section is locally consistent; only a
whole-document pass sees it.

**Genre fit.** For a paper, talk or thesis, the file under
`scientific-writing/genres/` fixes the reader and where depth goes; for
documentation, the reader step 1 named. Judge the section against it.

**Evidence routing.** Run the review checks in `scientific-writing`,
including inspecting the rendered figures.

## Red flags

| Thought                                                              | Reality                                                                                                                                         |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| "I'll draft it and see how it reads"                                 | Drafting is where an unnamed genre and reader become expensive. Name them first.                                                                |
| "The build passes, so the section is done"                           | That is the mechanical half of verify. The judged half has not run.                                                                             |
| "This citation is probably right"                                    | Probably is not a citation. Check it or cut the sentence.                                                                                       |
| "It's only a wording pass"                                           | If the wording carries the argument, it is a Document. Re-classify.                                                                             |
| "Pass: line edits, argument unchanged" (to skip the reverse outline) | The ledger runs in every class; see `scientific-writing` section 1.                                                                             |
| "I'll make the notation consistent at the end"                       | The end is when it is load-bearing in four sections. Fix it as you see it.                                                                      |
| "humanizer is for papers, not for this codebase"                     | It is for prose wherever prose lives -- a README, a docstring, a PR body. The prose hook stays silent on those, so invoking it there is on you. |
