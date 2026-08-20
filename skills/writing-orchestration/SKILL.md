---
name: writing-orchestration
description: Use when orchestrating a prose deliverable end to end -- a paper, thesis chapter, talk, or long-form documentation -- where no test can assert the result is correct. Carries what each spine step means for writing, the review axes a reader must judge, and how much ceremony the work needs.
---

# Writing Orchestration

<SUBAGENT-STOP>
If you were dispatched to draft one section, or to review one section, stop
here and do that. This file is the orchestrator's contract -- classification,
substitutions, and the review axes -- and none of it applies to writing a
single section. Reading it costs you context and changes nothing about your
job.
</SUBAGENT-STOP>

The numbered spine lives in the master `CLAUDE.md`, and it does not
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

Choosing this skill does not put the coding skills out of reach, and it
must not:

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

| Class    | Meaning                                                                  | Sequence                                                   |
| -------- | ------------------------------------------------------------------------ | ---------------------------------------------------------- |
| Pass     | Line edits to prose that already exists; the argument is not in question | Edit, then report what changed and why                     |
| Section  | A new subsection into a document whose argument already exists           | State the claim and its evidence in chat, get a nod, draft |
| Document | A new chapter or paper, or a restructure that changes the argument       | The full spine                                             |

When torn between two classes, take the heavier one. Discovering that a
"pass" is actually rewriting the argument upgrades the class: stop, say
so, re-classify. Nothing downgrades mid-task.

## What each step means

| Step         | For code                                         | For prose                                                                                               |
| ------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| 0 Preflight  | Tests green, clean tree, default branch          | The document builds today, clean tree, default branch. A build already broken hides what you break next |
| 1 Understand | A quantifiable success metric                    | The claim, the audience, the venue's page or word limit, and what a reader must believe by the end      |
| 2 Specify    | Interfaces and the tests that fix them           | An outline at paragraph granularity: each section's claim, its evidence, and its transition             |
| 3 Isolate    | Feature branch; worktree when phases parallelise | Unchanged                                                                                               |
| 4 Implement  | A subagent per phase, a fresh reviewer per phase | A draft per section; the reviewer reads that section and the outline, not the whole document            |
| 5 Verify     | Run the command, read the output                 | Builds clean, no undefined `\ref` or `\cite`, `chktex` quiet, inside the page budget                    |
| 6 Review     | code-review, then standards-and-spec-review      | The three axes below, then `humanizer`, then re-verify the build                                        |
| 7 Integrate  | PR or merge, then reflect                        | Unchanged                                                                                               |

Step 2 is where prose most often goes wrong. An outline that lists
section *topics* has decided nothing; one that states each section's
claim and the evidence for it has done the actual thinking, and drafting
from it is transcription. If the outline cannot say what a section is
for, drafting it will not discover the answer.

## The three review axes

`code-review` has no prose equivalent -- there is no compiler for a
claim -- so these replace it at step 6.

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

**Audience fit.** Name the audience before drafting, and say what naming
it licenses -- what may be assumed, what must be defined, what may be
cited instead of explained. A thesis committee, a referee, and a
colleague in another field need different amounts of the same argument.
Left unstated, the audience defaults to the writer, who already knows
everything and therefore needs nothing explained.

## Red flags

| Thought                                             | Reality                                                                                                                                         |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| "I'll draft it and see how it reads"                | Drafting is where an unnamed audience becomes expensive. Name it first.                                                                         |
| "The build passes, so the section is done"          | That is the mechanical half of verify. The judged half has not run.                                                                             |
| "This citation is probably right"                   | Probably is not a citation. Check it or cut the sentence.                                                                                       |
| "It's only a wording pass"                          | If the wording carries the argument, it is a Document. Re-classify.                                                                             |
| "I'll make the notation consistent at the end"      | The end is when it is load-bearing in four sections. Fix it as you see it.                                                                      |
| "The outline lists the sections, so step 2 is done" | Topics are not claims. An outline that decided nothing has not been written.                                                                    |
| "humanizer is for papers, not for this codebase"    | It is for prose wherever prose lives -- a README, a docstring, a PR body. The prose hook stays silent on those, so invoking it there is on you. |
