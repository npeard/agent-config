---
name: standards-and-spec-review
description: Use when reviewing a completed change against house standards and its originating spec - the two axes that correctness and quality review do not cover. Reports Standards and Spec findings side by side without merging them. Invoke per implementation phase as a cheap fresh-context reviewer, or per branch before integration.
compatibility: Requires Git and the project's verification commands. Parallel branch review additionally requires host support for subagents.
---

# Standards and Spec Review

Two axes that nothing else in the review chain covers:

- **Standards** -- does the change obey this project's documented rules?
- **Spec** -- does it actually implement what the spec asked for?

Built-in `code-review` finds correctness bugs and `simplify` finds
quality issues. Neither knows the house rules, and nothing else checks
spec fulfillment at all. Spec divergence is the failure mode most likely
to survive every other lens, because each individual line can look
correct.

**Report the two axes separately and never merge or re-rank them.** A
change can pass one while failing the other -- flawless conformance to
every rule while implementing the wrong thing, or the right behaviour
built in a way the project forbids. Combining the axes lets each mask
the other, which is the whole point of separating them.

## Modes

| Mode     | Scope                  | Spawns                                     | Used by                              |
| -------- | ---------------------- | ------------------------------------------ | ------------------------------------ |
| `phase`  | One phase's diff       | Nothing -- it is a leaf                    | A cheap per-phase reviewer subagent  |
| `branch` | `<fixed-point>...HEAD` | May run the two axes as parallel subagents | The orchestrator, before integration |

`phase` mode spawning nothing is a hard requirement, not a preference: a
per-phase reviewer that fanned out would be nesting subagent spawns
inside a subagent, and review cost would stop being linear in phases.

## Process

1. **Pin the fixed point.** Take the caller's ref (SHA, branch, tag,
   `HEAD~3`). Validate with `git rev-parse`, then diff with three dots
   -- `git diff <fixed-point>...HEAD` -- so the comparison is against
   the merge base rather than against unrelated drift on the other
   branch. Record `git log <fixed-point>..HEAD --oneline`. Stop if the
   diff is empty; say so rather than reviewing nothing.
2. **Load the standards.** Read `CODING_STANDARDS.md` next to this file
   -- the twelve house rules with examples, and the classic smell set as
   a fallback lens. Then layer the project's own `CODING_STANDARDS.md`
   or `CLAUDE.md` on top; project rules win where they disagree. Both
   binding rules for applying them live in that file, including the one
   that saves the most attention: skip whatever tooling already
   enforces.
3. **Locate the spec.** The orchestrator passes an absolute path,
   because specs live gitignored under `docs/superpowers/specs/` and a
   worktree does not contain the parent checkout's untracked files.
   Failing that, check commit messages for issue references. If no spec
   exists, report the Spec axis as "no spec available" -- do not
   reconstruct one from the diff, which would only confirm whatever was
   built.
4. **Run both axes**, then report them side by side.

## Standards axis

Apply `CODING_STANDARDS.md`. Cite the rule by name and quote the hunk.
Distinguish a hard violation from a judgement call, and say which.

Run `pixi run thresholds` before reading for rule 6. It reports
assertion bounds the diff loosened, which is the mechanical half of that
rule; a reviewer eyeballing diffs for widened thresholds is doing by
hand what a script already does, and the script was reachable from
nothing until this line existed.

Do not restate the rules here or in the report -- name them. A reviewer
that pastes the rulebook back at the reader buries its own findings.

## Spec axis

- **Missing or partial requirements.** Quote the spec line, then show
  what the diff does or does not do about it.
- **Scope creep.** Work the spec never asked for. Flag it even when it
  is good work -- it was not reviewed, tested, or agreed.
- **Silently narrowed scope.** The most valuable finding on this axis: a
  requirement satisfied for the easy case with the hard case quietly
  dropped. Check every quantifiable success metric the spec set and say
  whether it was met, missed, or never measured.
- **Stale spec.** If the implementation is right and the spec is wrong,
  that is a design bifurcation for the human, not a defect to fix.

## Report format

```
## Standards
<findings, each naming the rule and quoting the hunk;
 hard violations separated from judgement calls>

## Spec
<findings, each quoting the spec>

Standards: N findings, worst: <one line>
Spec: M findings, worst: <one line>
```

Rank within each axis, never across them. Keep each axis under roughly
400 words; a reviewer that returns an essay does not get read.

If an axis is clean, say so in one line. "No findings" is a real and
useful result, and padding it with speculative nits makes every future
clean report untrustworthy.
