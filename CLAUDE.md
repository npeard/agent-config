# CLAUDE.md (master)

Personal operational preferences that apply across all projects, loaded
automatically by Claude Code via `~/.claude/CLAUDE.md` (this file,
symlinked from `~/Documents/Projects/claude-config/CLAUDE.md`).
Project-specific `CLAUDE.md` files add to, not repeat, this content.

## Core philosophy

Every line of code carries ongoing comprehension and maintenance cost --
it must be read, understood, and kept correct as the codebase evolves.
Weigh that cost against the value a line provides:

- Write the smallest amount of code that does not sacrifice clarity of
  intent or process. Large diffs are inherently more difficult to
  comprehend and check for correctness.
- Comments and docstrings should explain the *why* (a hidden constraint,
  a non-obvious invariant, a workaround) -- the code itself already
  defines the *what* and the *how*.
- Reuse and generalize existing code before writing new code.
- Prefer standard-library or well-established third-party solutions over
  hand-rolled ones, unless there is a clear, specific reason the
  existing option doesn't fit.
- The same weighing applies to agent time: dispatch subagents in
  parallel for independent subtasks (many call sites, benchmarks, a
  sibling repo) rather than in sequence, at the cheapest model that
  holds accuracy. This holds for any task, not only ones running the
  workflow below.

## General Workflow

When orchestrating a task -- as opposed to executing one phase of a plan
someone else owns -- invoke the `workflow-orchestration` skill; it
carries the detail behind each step below, including how to brief a
subagent and when to stop. A subagent running a single phase should not
load it. Ceremony scales with the task -- `superpowers:brainstorming`
classifies it as spike, bounded, or architectural, and only
architectural work runs the full sequence.

0. **Preflight.** `pixi run preflight` (or the project equivalent):
   pre-commit installed and current, tests green, on the default branch,
   clean tree.
1. **Understand.** `superpowers:brainstorming`. Establish a quantifiable
   success metric -- a number and a baseline, or a named artifact.
   Surface conceptual and implementation gaps before they cost
   implementation time.
2. **Specify.** `superpowers:writing-plans`, with
   `superpowers:test-driven-development` fixing each phase's tests.
   Specify intent and interfaces, not source code. Specs stay
   gitignored, so hand subagents absolute paths.
3. **Isolate.** Commit any pre-existing WIP on the current branch before
   branching -- never carry it silently onto the new branch. Feature
   branch always; `superpowers:using-git-worktrees` when phases run in
   parallel.
4. **Implement.** `superpowers:subagent-driven-development` (this
   session) or `superpowers:executing-plans` (a separate session).
   `superpowers:dispatching-parallel-agents` for independent phases;
   `superpowers:systematic-debugging` the moment anything breaks. Commit
   per logical change as you go. Review each phase before the next with
   a fresh cheap reviewer running `standards-and-spec-review` in `phase`
   mode -- never the subagent that wrote it.
5. **Verify.** `superpowers:verification-before-completion` -- run the
   command and read the output before claiming anything.
6. **Review.** `code-review` at high effort, then filter its findings
   through `superpowers:receiving-code-review` before acting on any of
   them, then fix. Then `standards-and-spec-review` in `branch` mode for
   cross-phase house rules and spec fulfillment, then `simplify` -- it
   rewrites the tree itself -- then re-verify, since the tree you
   verified at step 5 no longer exists. Loop while findings remain.
7. **Integrate.** `superpowers:finishing-a-development-branch`. Ask
   whether to open a PR or merge locally; if a PR is opened, run
   `/code-review` on it as an independent second pass.

Stop for me at only two points: the finished spec (step 2) and the final
report (step 7). Between them act autonomously, overriding the
per-section gates in `brainstorming` and the checkpoints in
`executing-plans`. Break out early only for a genuine design
bifurcation, a spec proven unmeetable, or an irreversible or
outward-facing action. "I am uncertain" is not one of those: do the
parts that do not depend on it, state the assumption, continue.

## Agent evolution

- **Measure friction; do not rely on noticing it.** `pixi run friction`
  mines session transcripts for recurring failures, and `preflight`
  flags when a class crosses the bar. When one does, use the `reflect`
  skill to pick a tier and record the decision in
  `friction-ledger.toml`.
- **Prefer the cheapest durable tier:** nothing, then a hook, then a
  script, then a skill, and only last a rule here. Always-loaded prose
  is the most expensive option because every future session pays for it,
  so the default outcome is no new artifact -- usually because a rule
  already exists and was ignored, or a tool is working as designed. The
  ladder and the reasoning live in that skill.
- **Promote general taste to this repo.** If a preference, skill, script
  or hook would hold across projects rather than being tied to one
  project's domain or tooling, it belongs in
  `~/Documents/Projects/claude-config`, not only in project-local
  memory.

## Coding standards

Each rule below is defined, with a flag/prefer example, in the
`standards-and-spec-review` skill's `CODING_STANDARDS.md` -- which also
defines the classic smell set. That file is the single definition and is
read on demand; these lines are triggers, not restatements, so a rule
changes there and not here.

- **No hidden defaults** at call sites. Project-specific enforcement
  (e.g. a strict no-default-arguments rule for config dataclasses)
  belongs in that project's own CLAUDE.md.
- **Fix lint and type errors; do not suppress them.** A suppression
  stops the linter checking that line forever. Suppress only for a
  documented, narrow exception.
- **No tests that assert a refactor happened.**
- **No superseded implementation kept alive as a comparison oracle** --
  compare against a naive library method and record in prose why the old
  approach was discarded.
- **A benchmark baseline must do production's job**, or the comparison
  is meaningless.
- **Delete a flaky gate rather than loosening its threshold** -- a gate
  edited to keep passing trains people to ignore red. Prefer a
  deterministic structural assertion to a timed one.
- **Never hand-fix what a tool owns.** Run the project's own
  format/precommit command instead of editing by hand.
- **Comments record the why** -- see Core philosophy above; this is the
  same rule seen from the reviewer's side.
- **No speedup claimed from profiler percentages alone** -- confirm with
  a real wall-clock A/B, and if the result was neutral, say so.
- **Build new tools when a correction recurs.** If you keep re-fixing
  the same class of error, add the check to the project's CD workflow.
  Generic tools worth reusing across projects live in
  `~/Documents/Projects/claude-config/scripts/` -- copy from there
  rather than rewriting one that has already been built.

## Verification & perf philosophy

- **De-risk speculative performance work first.** Run a validation
  phase, show the results plainly regardless of outcome, and pause for
  explicit approval before continuing to implementation.

## Repo hygiene

- Gitignore `docs/superpowers/` (and any local `scratch/`) in every
  project. Brainstorming specs and execution plans are session-scoped
  scaffolding -- durable rationale belongs in commit messages, PR
  descriptions, and code comments, where it can't drift out of sync with
  the code.
