---
name: reflect
description: Use when recurring friction needs a durable fix - diagnoses why it recurs before deciding what to change, checks whether an existing tool or a missing standard one already answers it, and consolidates duplicated concepts. Run when `pixi run friction` reports actionable classes, at branch completion, or on request.
compatibility: Full operation requires this repository's Pixi tasks and Python scripts; transcript analysis currently supports Claude Code only.
---

# Reflect

Detection is mechanical and already done: `pixi run friction` mines
session transcripts and costs no context. Your job is the part that
needs judgement -- **why** this recurs, and only then what to change.

**Not a per-session retrospective.** Asked what was frustrating, a model
always answers, which is how a self-improvement loop becomes a skill
factory. Reflect when friction has crossed the bar -- `friction.py` owns
the threshold and prints it -- when a branch is finished, or when asked.

## The rule: name a cause before naming a tier

Choosing an artifact first restricts you to artifacts. It cannot notice
that the answer is a tool the project never installed, a script that
already exists, or a spec that failed to decide something.

State the cause in a sentence, then let it select the tier. The mapping
is most of the decision, which is the point -- it removes the
arbitrariness from tier choice.

| #   | Cause                 | Meaning                                                                          | Action                                          |
| --- | --------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------- |
| 1   | `missing-tooling`     | The project lacks a standard tool, so nothing was ever going to catch this class | Adopt the idiomatic tool (tier 1-2)             |
| 2   | `asset-not-adopted`   | claude-config already has a tested fix, just not installed here                  | Copy or adapt it (tier 2)                       |
| 3   | `rule-not-enforced`   | A documented rule exists and was not followed                                    | Make it mechanical (tier 1), or accept (tier 0) |
| 4   | `working-as-designed` | A tool caught something; one round trip bought a guarantee                       | Nothing (tier 0)                                |
| 5   | `harness-constraint`  | The environment refuses, and says so where it happens                            | Nothing (tier 0)                                |
| 6   | `underspecified-task` | Rework from ambiguity, not tooling. Downstream of a spec that never decided      | Fix the spec stage, not the code                |
| 7   | `claude-config-gap`   | None of the above; the config genuinely does not cover this                      | Brainstorm a new feature (tier 3-4, gated)      |

Check them in order. Cheap and mechanically-checkable causes come first;
`claude-config-gap` is last so it is only reached after ruling out that
a solution already exists.

**Cause 6 is the one no script can reach** and the one most often
mislabelled as a tooling problem. The tell is rework no tool could have
prevented: a decision never made, made late, or made twice. Repeated
user corrections usually land here.

**Cause 7 should feel like a real finding.** Reaching it means the
starter config disappointed the user, which is worth brainstorming
properly rather than patching with a quick rule.

## Diagnosing: look at what already exists

Run `pixi run toolgaps`. It reports missing standard tooling (cause 1)
and inventories claude-config's `scripts/`, `hooks/` and `skills/`
(cause 2). Read the master `AGENTS.md` for rules that already cover the
friction (cause 3).

### Then check for redundancy

If **several** assets look relevant, that is evidence they encode one
concept in different words. This is conceptual, not textual -- two
artifacts can share no phrasing and still do one job, so grep will not
find it. Four tests:

- **Substitution.** Could one be deleted and the other cover the case?
- **Trigger overlap.** Would both apply to the same situation? Then a
  reader has to choose, and will sometimes choose wrong.
- **Same failure prevented.** Different words aimed at one failure mode
  is duplication, not defence in depth.
- **Boundary sentence.** Can you state what separates them in one
  sentence? If yes they are distinct. If you cannot, they are one
  concept wearing two names. This is the guard against over-merging:
  consolidating things that were actually distinct produces a worse
  artifact than leaving both.

| Situation                             | Resolution                                                                                         |
| ------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Same concept, both prose              | One definition; others name it and point at it                                                     |
| Prose now covered by a hook or script | **Delete the prose.** A hook does not gate on context, so the rule is redundant, not complementary |
| Two scripts overlapping               | One owns the check; the other drops it and defers                                                  |
| Two skills overlapping                | Merge, or split on a boundary you can state in one sentence                                        |

Consolidation is also the budget's release valve. When a tier-4 proposal
has no room, the eviction candidate is usually a duplicate rather than
something still earning its place -- so a failing budget test is a
reason to run this check across every asset, not just the ones one
friction made relevant.

## Prescribing: why hooks outrank skills and prose

A hook does not gate on context. It fires regardless of what the model
remembered, what got compacted away, which skill happened to be invoked,
or how long the session ran. A rule in `AGENTS.md` and a skill are both
*requests to behave*; a hook is a *fact about the system*. So a
mechanical fix belongs in a hook even when writing the rule would be
faster: the rule's compliance decays and the hook's does not.

| Tier | Artifact             | Cost                   | Autonomy                                          |
| ---- | -------------------- | ---------------------- | ------------------------------------------------- |
| 0    | Nothing              | none                   | Autonomous                                        |
| 1    | Hook                 | none                   | Autonomous, **tests required**                    |
| 2    | Script or task       | none until run         | Autonomous, **tests required**                    |
| 3    | Skill                | on demand              | Approval, then `brainstorming` + `writing-skills` |
| 4    | Prose in `AGENTS.md` | every session, forever | Approval                                          |

Tier 0 is the expected outcome, not a failure. The ladder also points
**downward**: a skill that turns out to be purely mechanical should
become a hook or script and then be deleted.

"Tests required" is not optional at tiers 1-2. An untested hook is how
`promotion-check` silently never fired for months.

### The tier-3 path

Never write the skill yourself. After approval, run
`superpowers:brainstorming` to design it, then
`superpowers:writing-skills` to build and verify it -- that skill owns
directory layout, description wording, and verifying the skill actually
fires. It also carries its own skill-worthiness bar; **if it says do not
create this, honour that** and drop back down the ladder, recording the
outcome. It covers editing and deleting skills too, which is what the
downward direction of the ladder needs.

## Process

1. `pixi run friction --review`, or take the friction from the branch
   just finished.
2. `pixi run toolgaps` for missing tooling and available assets.
3. For each class: read the example, not just the class name. Walk
   causes 1-7 in order. Write the cause down.
4. If several assets look relevant, run the redundancy check.
5. Take the tier the cause implies. Before any tier-4 proposal, check
   the budget: if there is no room, name what comes out or choose a
   lower tier. "Raise the ceiling" is not an answer.
6. Record every decision in `friction-ledger.toml` with `cause`,
   `outcome` and `count_at_decision`. A decision missing the count
   suppresses its class forever, which is how this goes blind while
   looking healthy.
7. Report what you decided and what you rejected. A pass that changes
   nothing is a successful pass.

## Red flags

| Thought                                                       | Reality                                                     |
| ------------------------------------------------------------- | ----------------------------------------------------------- |
| "Which tier should this be?"                                  | You skipped the cause. Name it first.                       |
| "This session had friction, let me write a skill"             | One session is one incident. Check the bar.                 |
| "I'll add a line to AGENTS.md, it's only a line"              | Every future session reads it forever. Tier 4 is last.      |
| "The rule exists but nobody follows it, so restate it louder" | Restating changes nothing. Make it mechanical or accept it. |
| "Both of these tools are relevant"                            | Then check whether they are the same concept.               |
| "These two feel similar, I'll merge them"                     | State the boundary first. If you can, they are distinct.    |
| "I'll raise the word ceiling to fit this"                     | The ceiling is the mechanism. Evict instead.                |
| "I'll write the new skill now"                                | `brainstorming` then `writing-skills`. Never freehand.      |
| "Nothing crossed the bar, so I have nothing to report"        | Correct. Say so and stop.                                   |
| "Tier 0 means I found nothing"                                | Tier 0 is the most common correct answer.                   |
