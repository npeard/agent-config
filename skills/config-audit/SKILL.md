---
name: config-audit
description: Use when a branch has changed agent-config's own skills, scripts, hooks or AGENTS.md, or when `.audit-owed` exists - judges the assembled agent config against the five agent-asset principles, on the axes no mechanical check can reach.
compatibility: Requires this repository's Pixi environment and audit scripts. Git is required for branch-relative findings and audit obligations.
---

# Config audit

Every other review mechanism here looks at a change. `code-review` finds
bugs in a diff, `standards-and-spec-review` checks a diff against house
rules, `reflect` diagnoses a friction that already happened. None of
them ever looks at the whole installed set and asks whether it still
earns what it costs.

One sentence for the boundary against the nearest neighbour: **`reflect`
asks why something went wrong; this asks whether the system as assembled
is still worth what it costs.** No incident required.

The five principles are defined in `AGENT_ASSET_PRINCIPLES.md`, read on
demand. This file is the process.

## Run the script first

```
pixi run audit          # human table
pixi run audit --json   # for reasoning over
```

Reason from its output. Do not re-read every asset to form your own view
of what it already told you -- principle 3 applies to the auditor, and
the mechanical pass is the cheap half by construction.

`pixi run audit --owed` lists what the marker has recorded since it was
last cleared -- not necessarily everything the branch changed, since
clearing mid-branch resets it. For the branch's true scope use
`git diff --name-only main...HEAD`.

`--help` for the rest. `--sha <asset>` gives the hash a ledger entry
needs, so writing one never requires opening the script.

## What the script cannot see

The whole value of this skill is in these three rows. Everything else is
already a test.

| Axis          | The question                                                                                                               | Why no script can answer it                                                                            |
| ------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Evidence (P2) | Does each gotcha, red-flag row and prohibition trace to something that actually happened -- or was it invented by analogy? | A fabricated example has the same shape as a remembered one.                                           |
| Security (P5) | Is a flagged read-and-emit path actually exploitable, and what is the right trust boundary?                                | The check reports a conjunction. It cannot see a mitigation already in place, or judge severity.       |
| Coherence     | Do any two assets encode one concept in different words?                                                                   | Conceptual, not textual: two artifacts can share no phrasing and do one job, so grep will not find it. |

For coherence, run `reflect`'s four redundancy tests -- substitution,
trigger overlap, same failure prevented, boundary sentence -- across the
whole set rather than against one friction. The boundary sentence is the
guard in both directions: if you can state in one sentence what
separates two assets, they are distinct and merging them makes a worse
artifact.

## Suspect the check before the asset

When a flagged asset looks compliant, the check is the likelier defect,
and a check that punishes compliance with one principle in the name of
another is worse than no check at all.

Two of these were found on the first real run. The P2 check knew tables
and code fences only, and reported `humanizer` -- whose entire catalog
is labelled before/after pairs -- as evidence-free, punishing the very
split principle 3 asks for. The P4 check read `[tasks]` and not
`[feature.dev.tasks]`, and reported six real tasks as dangling.

Fix the check and add a regression test for the compliant shape it
misjudged. Do not ledger a false positive: a ledger entry says "this
finding is real and accepted", which is a different claim.

## What this skill may not do

**It may not propose or write a new skill.** It reports; `reflect` owns
the tier ladder and its own skill-worthiness bar. Without that boundary
this becomes the skill factory `reflect` exists to prevent -- and the
falsification test is written down: if three consecutive audits each
produce a new asset, the mitigation has failed and this feature should
be reconsidered rather than defended.

**It spawns nothing.** It is a leaf, so audit cost stays linear in the
number of assets rather than multiplying.

## Recording decisions

Every finding ends as one of two things, and never as a note in chat:

- **A fix.** The asset changes.
- **A ledger entry** in `audit-ledger.toml`, keyed asset + principle,
  with a `cause` from `reflect`'s taxonomy and the asset's `asset_sha`.

The hash is the convergence mechanism. `friction-ledger.toml` reopens a
class when its count doubles, because a friction is an event stream; an
audit finding is a statement about a file, so the exception expires when
the file changes. Write the note that states *that asset's* actual trust
boundary or rationale. A formula copied across five entries records
nothing, and is worse than an empty ledger because it looks decided.

**Re-grant once, at branch end, against the asset's final state.** An
exception whose asset the branch has edited reports as *awaiting
re-grant* rather than as a failure -- `pixi run audit` names those
assets and exits 0, and the same finding fails on the default branch,
where the work has landed. So there is nothing to fix mid-branch and
nothing to keep green. Re-granting per commit re-judges an asset that is
about to change again, and the note pays for it: the entry on
`hooks/notify.py` reached 55 lines across four re-grants in one branch,
about 20 of them describing what earlier drafts of those same lines had
got wrong.

**The note states the boundary as it now stands, not how it got there.**
Git holds the drafts; a reader wants what the code enforces today. Write
"markers live in a uid-named subdirectory, and arming is
`O_CREAT|O_EXCL`" -- not "an earlier version of this note claimed the
temp directory was per-user, which was false." One exception: a mistake
a future editor would otherwise reintroduce is worth keeping, as a
statement about the code -- "`mkdir(exist_ok=True)` is satisfied by a
symlink, so it cannot establish a private directory" -- never as a
correction to a previous note.

Then clear the marker: `pixi run audit --clear-owed`. This is not
tidying. `preflight` reports on the marker's presence, not on whether an
audit ran, so a marker nobody clears becomes a standing warning -- and a
warning that is always there is one everyone learns to scroll past,
which is the same failure as a gate loosened to keep passing.

A pass that changes nothing is a successful pass. Say so and stop.

## Red flags

| Thought                                               | Reality                                                                                                                                                                                                                      |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "The audit found nothing, so it was wasted"           | Tier 0 is the expected outcome. Report it and stop.                                                                                                                                                                          |
| "This asset needs a new skill"                        | Not yours to propose. Hand it to `reflect`.                                                                                                                                                                                  |
| "I'll read each skill and judge it myself"            | The script already did the mechanical pass. Read its JSON.                                                                                                                                                                   |
| "The report is noisy, I'll loosen the check"          | Only if the check misjudged a compliant asset. Otherwise ledger the exception with a cause, so it expires when the asset changes.                                                                                            |
| "I'll ledger this false positive to quiet it"         | A ledger entry claims the finding is real and accepted. Fix the check instead, and add a regression test.                                                                                                                    |
| "Every P5 candidate gets the same note"               | Then the notes record nothing. State each asset's actual boundary.                                                                                                                                                           |
| "This note states a real boundary, so it is settled"  | Re-test the boundary, do not re-read the note. `task-list.py`'s said the payload was capped at 60 characters; the cap was on the definition, never the name, and `asset_sha` could not expire a premise that was never true. |
| "This asset is under its ceiling, so it is fine"      | A ceiling bounds growth. It does not make content worth reading.                                                                                                                                                             |
| "These two skills feel similar, I'll merge them"      | State the boundary first. If you can state it, they are distinct.                                                                                                                                                            |
| "I'll skip the ledger and mention it in the report"   | The report is gone next session. The ledger is what stops re-litigation.                                                                                                                                                     |
| "The audit is done, I'll leave the marker"            | `preflight` warns on presence, not completion. `pixi run audit --clear-owed`.                                                                                                                                                |
| "The audit is red, I'll re-grant now to get it green" | Read it again. An exception on an asset this branch changed is *awaiting*, exits 0, and is due once at branch end. Re-granting to clear a warning that is not there is the churn this section exists to stop.                |
| "I should record how the previous note was wrong"     | No. Git holds the drafts. State the boundary the code enforces now; keep a past mistake only as a constraint on the code, never as a correction to a note.                                                                   |
