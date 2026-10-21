---
name: workflow-orchestration
description: Use when orchestrating an engineering or research task end-to-end - carries the sequence from problem definition through spec, delegated implementation, review, and integration, and defines which approval gates apply. Invoke before brainstorming, not after. Not for a subagent executing or reviewing a single phase.
compatibility: Requires Superpowers, Git, subagents, and worktrees.
---

# Workflow Orchestration

<SUBAGENT-STOP>
If you were dispatched to execute one phase, or to review one phase, stop
here and do the task you were given. This file is the orchestrator's
contract -- delegation, gates, and the review loop -- and none of it applies
to executing a single phase. Reading it costs you context and changes
nothing about your job.
</SUBAGENT-STOP>

The numbered spine lives in the master `AGENTS.md`. This skill carries
the detail behind each step: which skill to invoke and why that one, how
to brief a subagent, and when to stop. Cases cited as "example N" live
in `examples.md`.

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

This deliberately **overrides** `brainstorming`'s per-section approvals
and `executing-plans`'s per-phase checkpoints, which exist for
supervised use. Consolidate them into the step 2 gate.

Break out early only for:

- A **genuine design bifurcation** -- two defensible paths whose choice
  changes the deliverable, not merely a detail you could pick and note.
  A question whose "ship as-is" option is viable is not one: take it,
  note it, ask at step 7.
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
project has no such script, install agent-config's exported `preflight`.

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
spec, and see the master `AGENTS.md` on what not to test (no tests that
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
commands; the *names* of any skills it should invoke; and these
instructions:

- Run the project's format/precommit itself before reporting. The
  orchestrator running the formatter is a smell -- a subagent stopped
  early.
- Launch a job that outlasts a few minutes detached and return; see
  `compute-job-safety`'s "Long jobs".
- Batch independent shell commands into one call; each costs over a
  second of harness overhead (example 4).
- Run the narrowest test target that covers the change; the full suite
  runs once, at step 5 (example 3).

Name skills, never quote them -- reading one to brief someone else pays
for it twice, and the orchestrator is the expensive place to pay. Name
`standards-and-spec-review` and the mode; let the reviewer load it.

**Review each phase before starting the next.** When a phase subagent
reports, the orchestrator dispatches a *separate* cheap reviewer running
`standards-and-spec-review` in `phase` mode over that phase's diff, and
its findings are fixed before moving on. Batched to the end, a phase 1
defect gets built on by phases 2 and 3.

| Reviewer              | Model                        | Context                              | Owns                                                                     |
| --------------------- | ---------------------------- | ------------------------------------ | ------------------------------------------------------------------------ |
| Per-phase             | Cheapest that holds accuracy | Fresh: phase diff + spec + standards | Standards conformance, spec fulfillment for that phase                   |
| Orchestrator (step 6) | Session model                | Whole branch                         | Architecture, cross-phase coherence, whether the spec was the right spec |

Two constraints that are the whole point of the split:

- **The reviewer is never the implementer.** A subagent reviewing its
  own output shares the assumptions that produced it, so it ratifies
  rather than finds. The implementer's self-check is mechanical only --
  precommit ran, the spec's tests exist, the brief is met.
- **The per-phase reviewer spawns nothing.** It is a leaf (hence `phase`
  mode); one that fanned out would make review cost nonlinear in the
  number of phases.

**Fix rounds resume the implementer only while it is small.** This
overrides `subagent-driven-development`'s "resume rounds 1-3". A resume
re-reads the whole context every turn, so past the `agent-resume-size`
hook's cap dispatch a fresh fix agent with the previous report file, the
findings and the diff range (example 2). **After a usage- or
session-limit pause, always dispatch fresh**: the cache is cold, so a
resume rewrites the whole context (example 1).

**Model tier:** the cheapest model that holds accuracy. Mechanical
search, call-site updates and file moves need no frontier model;
design-sensitive work and review do. Wrong upward wastes tokens, wrong
downward a whole round trip.

**Commit as you go**, one logical change per commit, messages explaining
*why*. A large uncommitted pile at the end forecloses bisecting and
reverting.

### 5. Verify -- `superpowers:verification-before-completion`

Evidence before assertions, always. Run the command, read the output,
then claim. For long-running scripts, smoke-verify under a timeout and
confirm the metric is moving the right way; being killed by the timeout
is expected, not a failure.

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
   review cannot see. Skip axes covered per phase only if every phase
   was reviewed. **Dispatch its two axes as parallel subagents**: they
   read the same diff and never need each other's output. That skill
   sanctions this in `branch` mode only; `phase` mode is a leaf.
5. `simplify` -- reuse, simplification, efficiency. This one *applies*
   its own edits rather than reporting them, so it cannot be gated by
   the filter above; read its diff and revert brevity that costs
   clarity.
6. **Re-run Verify (step 5).** The fix subagent and `simplify` have both
   rewritten the tree, so the tree that was verified before this step is
   not the tree that exists now.
7. Loop only on surviving correctness findings, over the fix diff.

**A fix that adds a subsystem re-enters at step 4, not step 6.** Read
*where* the findings are: spread across the branch, the review is
working. Massed in the code answering the last round, the fix added
machinery -- which owes tests and a phase review first.

**Scope each re-review to the fix diff; loop on correctness only.** A
reviewer asked for uncertain findings always returns some, so an
unscoped loop has no fixed point; quality findings belong to `simplify`.
Leave when no correctness finding survives and verification passes.
Escalate, reporting the state plainly, when the same finding recurs
after two fix attempts, a finding implies the spec was wrong, or three
full rounds have completed.

**A capacity error is not a round.** An HTTP 529 or a timeout means the
review never ran: retry with backoff, and count it neither as a round
nor as thrash.

### 7. Integrate -- `superpowers:finishing-a-development-branch`

Ask whether to open a PR or merge locally -- do not assume. If a PR is
opened, run the `/code-review` command on it: it is a genuinely
different analysis from step 6, reading git blame and prior PR comments
on the touched files with confidence-scored findings, so it catches
historical-context problems a local diff review structurally cannot.

Before the final report, check the README and top-level docs for claims
the branch made false; the README holds no transient information.
Durable rationale belongs in commit messages and the PR body, not the
uncommitted spec.

**Then invoke `reflect`, once.** A finished branch is the cheapest
moment to diagnose friction: a whole task's worth of evidence exists and
the corrections that happened are still recallable. It is bar-gated, so
most passes end with nothing to change -- which is a successful pass,
not a wasted one.

**And `config-audit` if the branch touched agent-config's own assets**
-- `.audit-owed` records that. A different question from `reflect`: not
why something went wrong, but whether the system still earns its cost.

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
| "This round's findings are all in last round's fix"           | Then it added a subsystem. Step 4, with tests.                 |
| "I'll just check they still want the default"                 | If the status quo is viable, take it. Ask at step 7.           |
| "I'm unsure, I should ask"                                    | Only if it blocks. Otherwise assume, state it, continue.       |
