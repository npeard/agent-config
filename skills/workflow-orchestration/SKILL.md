---
name: workflow-orchestration
description: Use when orchestrating a substantive engineering or research task end to end - carries the sequence from problem definition through spec, delegated implementation, review, and integration, and defines which human approval gates apply. Invoke before brainstorming, not after. Not for a subagent executing or reviewing a single phase.
---

# Workflow Orchestration

<SUBAGENT-STOP>
If you were dispatched to execute one phase, or to review one phase, stop
here and do the task you were given. This file is the orchestrator's
contract -- delegation, gates, and the review loop -- and none of it applies
to executing a single phase. Reading it costs you context and changes
nothing about your job.
</SUBAGENT-STOP>

The numbered spine lives in the master `CLAUDE.md`. This skill carries
the detail behind each step: which skill to invoke and why that one, how
to brief a subagent, and when to stop.

## Ceremony scales; the gates do not

Do not run all eight steps on every task. `superpowers:brainstorming`
classifies the work first, and the classification decides the ceremony:

| Class         | Meaning                                                         | Sequence                                        |
| ------------- | --------------------------------------------------------------- | ----------------------------------------------- |
| Spike         | A feasibility question whose output is an answer, not kept code | State the probe, get a nod, investigate, report |
| Bounded       | A well-scoped change to a flow that already exists in the repo  | Short design in chat, nod, then steps 3-7       |
| Architectural | New subsystem, or a change to an interface others depend on     | All of 0-7                                      |

When torn between two classes, take the heavier one. Discovering hidden
complexity mid-task upgrades the class: stop, say so, re-classify.
Nothing downgrades mid-task.

## Gate policy

**Stop for the user at exactly two points:** the finished spec (step 2)
and the final report (step 7).

This deliberately **overrides** the gates written into the skills below
-- `brainstorming` asks for approval after each design section, and
`executing-plans` adds per-phase checkpoints. Those exist for supervised
use; this workflow is explicitly configured for autonomous use, and the
user has approved the override. Consolidate them into the step 2 gate.

Break out early only for:

- A **genuine design bifurcation** -- two defensible paths whose choice
  changes the deliverable, not merely a detail you could pick and note.
- A spec proven **unmeetable**. Report what was attempted and why.
- An **irreversible or outward-facing action**: pushing, opening a PR,
  posting anything, deleting data, touching a remote.

"I am uncertain" is not a gate. Do the parts that do not depend on the
uncertainty, then state the assumption you made and continue.

## Step detail

### 0. Preflight

`pixi run preflight` (or the project's equivalent). Add `--with-tests`
when starting fresh work; add `--check-updates` weekly rather than every
session, since it costs a network round trip per hook repo. If the
project has no such script, copy `scripts/preflight.py` from
`claude-config`.

### 1. Understand -- `superpowers:brainstorming`

Invoke it *before* exploring the codebase, not after: it governs how to
explore. Two obligations beyond the skill's own text:

- **Force a quantifiable success metric.** "Faster" and "cleaner" are
  not metrics. Push until there is a number and a baseline, or an
  explicit artifact ("a report answering X"). Do not proceed without
  one.
- **Hunt for gaps preemptively.** Assume the user knows the outcome they
  want and some obstacles, but not necessarily what the code already
  contains. Surface conceptual and implementation gaps now; a gap found
  during implementation is one the user could have triaged in a
  sentence.

### 2. Specify -- `superpowers:writing-plans`

The spec is a handoff artifact for subagents, so it is written for a
reader with no conversation context. Use
`superpowers:test-driven-development` to fix each phase's tests in the
spec, and see the master `CLAUDE.md` on what not to test (no tests that
merely assert a refactor happened; no superseded implementation kept
alive as an oracle).

Specify *intent and interfaces*, not source code. A subagent that is
handed code transcribes it; one that is handed a clear contract and its
tests arrives at the implementation and catches spec errors on the way.

Specs stay gitignored under `docs/superpowers/`, so **hand subagents
absolute paths** -- a worktree does not contain the parent checkout's
untracked files, though it can read them by absolute path.

### 3. Isolate -- `superpowers:using-git-worktrees`

Feature branch always. Worktrees only when phases run in parallel and
would otherwise collide in the same tree; they cost setup time and disk,
so a purely sequential plan does not need them.

### 4. Implement

Pick the mechanism deliberately:

| Skill                                     | Use when                                                       |
| ----------------------------------------- | -------------------------------------------------------------- |
| `superpowers:subagent-driven-development` | Executing the plan in *this* session. The default.             |
| `superpowers:executing-plans`             | Handing a written plan to a *separate* session.                |
| `superpowers:dispatching-parallel-agents` | Fanning out 2+ phases with no shared state or ordering.        |
| `superpowers:systematic-debugging`        | The moment anything breaks. Before proposing a fix, not after. |

**Every subagent brief contains:** the absolute path to the spec; which
phase it owns and which phases are already done; the project's task
commands; the *names* of any skills it should invoke; and the
instruction to run the project's format/precommit itself before
reporting. The orchestrator running the formatter is a smell -- it means
a subagent stopped early.

Name skills, never quote them. Reading a skill in order to brief someone
else pays for it twice -- once in this context and again in theirs --
and the orchestrator is the expensive place to pay. Dispatch the
per-phase reviewer by naming `standards-and-spec-review` and the mode;
let the reviewer load it.

**Review each phase before starting the next.** When a phase subagent
reports, the orchestrator dispatches a *separate* cheap reviewer running
`standards-and-spec-review` in `phase` mode over that phase's diff. Fix
what it finds, then move on. Do not batch this to the end: a standards
or spec defect in phase 1 gets built on by phases 2 and 3, and unwinding
it later costs more than the review did.

| Reviewer              | Model                        | Context                              | Owns                                                                     |
| --------------------- | ---------------------------- | ------------------------------------ | ------------------------------------------------------------------------ |
| Per-phase             | Cheapest that holds accuracy | Fresh: phase diff + spec + standards | Standards conformance, spec fulfillment for that phase                   |
| Orchestrator (step 6) | Session model                | Whole branch                         | Architecture, cross-phase coherence, whether the spec was the right spec |

Two constraints that are the whole point of the split:

- **The reviewer is never the implementer.** A subagent reviewing its
  own output shares the assumptions that produced it, so it ratifies
  rather than finds. The implementing subagent's self-check is
  mechanical only -- did precommit run, are the spec's tests present, is
  the brief satisfied -- and is never the source of findings.
- **The per-phase reviewer spawns nothing.** It is a leaf, which is why
  `standards-and-spec-review` has a `phase` mode. A reviewer that fanned
  out would nest subagent spawns and review cost would stop being linear
  in the number of phases.

This is what keeps the expensive model out of line-level work. The
orchestrator should arrive at step 6 having already had conformance
checked per phase, free to spend its context on whether the pieces fit
together.

**Model tier:** use the cheapest model that will hold accuracy.
Mechanical search, call-site updates, and file moves do not need a
frontier model; design-sensitive implementation and review do. Getting
this wrong upward wastes tokens; getting it wrong downward wastes a
whole round trip, so prefer the cheaper tier only when the task is
genuinely mechanical.

**Commit as you go**, one logical change per commit. Messages explain
*why*; the diff already shows what and how. A large uncommitted pile at
the end is a failure of this step, not a tidiness preference -- it
forecloses bisecting and reverting.

### 5. Verify -- `superpowers:verification-before-completion`

Evidence before assertions, always. Run the command, read the output,
then claim. For long-running scripts, smoke-verify under a timeout and
confirm the metric is moving the right way -- being killed by the
timeout is the expected outcome, not a failure.

### 6. Review

Order matters here, and the obvious order is wrong:

1. `code-review` at high effort -- correctness bugs. Do not act on the
   output yet.
2. Filter those findings through `superpowers:receiving-code-review`.
   Review output is not automatically correct; verify each finding
   against the code and discard what does not survive.
3. Dispatch a fix subagent for the survivors.
4. `standards-and-spec-review` in `branch` mode over the whole branch --
   house rules and spec fulfillment across phases, which per-phase
   review cannot see. Skip the axes already covered per phase only if
   every phase was reviewed; otherwise this is the first standards pass.
5. `simplify` -- reuse, simplification, efficiency. This one *applies*
   its own edits rather than reporting them, so it cannot be gated by
   the filter above; read the diff it produces and revert anything that
   buys brevity at the cost of clarity.
6. **Re-run Verify (step 5).** The fix subagent and `simplify` have both
   rewritten the tree, so the tree that was verified before this step is
   not the tree that exists now.
7. If step 1 has new findings to report, loop.

**Loop exit conditions.** Leave the loop when review yields no surviving
findings and verification passes. Escalate to the user instead when: the
same finding recurs after two fix attempts (thrash, not progress); a
finding implies the spec was wrong (that is a design bifurcation); or
three full rounds have completed without converging. Report the state
plainly rather than looping silently.

### 7. Integrate -- `superpowers:finishing-a-development-branch`

Ask whether to open a PR or merge locally -- do not assume. If a PR is
opened, run the `/code-review` command on it: it is a genuinely
different analysis from step 6, reading git blame and prior PR comments
on the touched files with confidence-scored findings, so it catches
historical-context problems a local diff review structurally cannot.

Durable rationale belongs in the commit messages and PR body, not in the
spec file -- the spec is session-scoped scaffolding and is not
committed.

**Then invoke `reflect`, once.** A finished branch is the cheapest
moment to diagnose friction: a whole task's worth of evidence exists and
the corrections that happened are still recallable. It is bar-gated, so
most passes end with nothing to change -- which is a successful pass,
not a wasted one.

## Red flags

| Thought                                                       | Reality                                                        |
| ------------------------------------------------------------- | -------------------------------------------------------------- |
| "I'll explore the code first, then brainstorm"                | Backwards. Brainstorming governs how you explore.              |
| "The metric is obviously 'make it better'"                    | Not a metric. Go back to step 1.                               |
| "I'll put the code in the spec so the subagent gets it right" | A transcribing subagent catches nothing. Specify the contract. |
| "The subagent's work looks fine, I'll just run the formatter" | It stopped early. Find out why.                                |
| "The subagent reviewed its own work and it is clean"          | Self-review ratifies. Dispatch a fresh reviewer.               |
| "I will review all the phases at the end"                     | Phase 1's defect is load-bearing by phase 3. Review per phase. |
| "Review found nothing, so I'm done"                           | Did you re-verify after `simplify` mutated the tree?           |
| "The reviewer said it, so I'll fix it"                        | Filter through `receiving-code-review` first.                  |
| "I'll commit it all at the end"                               | Forecloses bisect and revert. Commit per logical change.       |
| "Round four will converge it"                                 | Three rounds without convergence is a report, not a loop.      |
| "I'm unsure, I should ask"                                    | Only if it blocks. Otherwise assume, state it, continue.       |
