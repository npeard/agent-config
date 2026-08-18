# CLAUDE.md (master)

Personal operational preferences that apply across all projects, loaded
automatically by Claude Code via `~/.claude/CLAUDE.md` (this file,
symlinked from `~/Documents/Projects/claude-config/CLAUDE.md`).
Project-specific `CLAUDE.md` files add to, not repeat, this content.

## Core philosophy

Every line of code carries ongoing comprehension and maintenance cost -- it must be read,
understood, and kept correct as the codebase evolves. Weigh that cost
against the value a line provides:

- Write the smallest amount of code that does not sacrifice clarity of
  intent or process. Large diffs are inherently more difficult to comprehend
  and check for correctness.
- Comments and docstrings should explain the *why* (a hidden
  constraint, a non-obvious invariant, a workaround) -- the code itself
  already defines the *what* and the *how*.
- Reuse and generalize existing code before writing new code.
- Prefer standard-library or well-established third-party solutions over
  hand-rolled ones, unless there is a clear, specific reason the existing
  option doesn't fit.

## General Workflow Guidance

- **Commit hygiene.** Before starting a new branch, commit any
  pre-existing uncommitted/WIP changes on the current branch first -- do
  not carry them silently into the new branch. Make incremental commits
  as you go (one logical change per commit) rather than leaving a large
  uncommitted pile. As with comments around code, commit messages should explain the context for *why* the change was performed; the diff already shows *what* was changed and *how*.
- **Fan out on independent work.** Dispatch subagents in parallel for
  independent subtasks (updating many call sites, running benchmarks,
  setting up scripts in a sibling repo) instead of doing them
  sequentially. Attempt to use the minimum subagent model that can complete the task with high accuracy (e.g. prefer Haiku over Sonnet for basic search and refactor, saving Sonnet for more complex tasks).
- **Use the project's short-form task commands.** Invoke `pixi run x`,
  `task x`, `npm run x`, etc. directly -- never the verbose underlying
  invocation (e.g. not `python3 -m taskipy x`).
- **No hidden defaults.** Prefer explicit values over hidden defaults at call sites, as a general
  taste: hidden defaults let behavior silently change without the call
  site noticing. Project-specific enforcement of this (e.g. a strict
  no-default-arguments rule for config dataclasses) belongs in that
  project's own CLAUDE.md.

## Agent evolution

- **Keep memory, skills, and CLAUDE.md in sync with this repo.** Whenever
  you write or update a memory file, create a new skill, or edit a
  project CLAUDE.md, pause and check: is this general engineering or
  workflow taste that would hold across projects, or is it tied to this
  project's domain, framework, or tooling? If general, also add it to
  `~/Documents/Projects/claude-config` (this file or `skills/`) and
  commit there, rather than letting it accumulate only in local,
  project-scoped memory.
- **Upgrade workflow memories and skills to hooks.** Frequently used skills, memories, or workflows that do not require user input and are mainly mechanical (e.g., remember to check formatting and linting before commits) should be upgraded to a process hook so that agent context may be reduced and used for less automatable tasks. Agent context is expensive and manual agent actions are slow; agents should not be weighed down by automatable actions and we should identify opportunities to create fast automated tools that an agent can utilize in a hook instead of program manually with prompts or context.

## Testing and benchmarking

- **No bridge API tests.** When refactoring a code base, do not invent tests that
  trivially verify the refactor has been performed (e.g., checking that a module does not exist).
- A benchmark baseline must do the same job as production, or the
  comparison is meaningless (e.g. don't compare a pre-assembled matrix
  against one that production reassembles every call).
- Never keep a superseded implementation alive as a comparison oracle -- compare
  against a naive library method instead, and record why the old
  approach was discarded in prose.
- When a benchmark gate proves flaky, delete it and document the
  measurement instead of lowering the threshold until it passes -- a
  flaky gate trains people to ignore red. Prefer a deterministic
  structural assertion over a timed one where possible.

## Linting, style, and continuous development

- **Use automated linting, formatting, and style tools.** Do not perform
  manual linting, formatting, or style fixes where a CD tool already does
  the job (the project's own format/precommit command, e.g. `pixi run
  format`, `ruff check --fix`, `pre-commit run --all-files`) -- run the
  tool instead of hand-editing.
- **Build new tools when a correction recurs.** If you find yourself
  making and re-fixing the same class of linting, formatting, or style
  error, ask whether it is frequent or mechanical enough to check or fix
  automatically, and add that check to the project's CD workflow (e.g. a
  pre-commit hook). Generic tools worth reusing across projects live in
  `~/Documents/Projects/claude-config/scripts/` -- copy from there rather
  than rewriting a tool that's already been built once.
- Fix lint and type errors in the code rather than suppressing them.
  Suppress only for well-understood, narrow exceptions (e.g. a project's
  documented notation convention) -- not to make a warning go away.

## Verification & perf philosophy

- **Smoke-verify long-running scripts on a timeout.** To check that a
  change works in a training/simulation script that runs for minutes or
  hours, run it under a short timeout and confirm it started cleanly and
  the loss (or equivalent metric) is descending -- do not wait for the
  script to exit. Being killed by the timeout is the expected outcome,
  not a failure. Read the head of the output for setup and the first
  epochs; don't pipe through `tail` waiting for a completion banner.
- Don't trust profiler percentages on tiny, high-frequency operations --
  cProfile's per-call bookkeeping inflates their apparent cost. Confirm
  any claimed micro-optimization with a real wall-clock A/B (several
  runs, report variance) before committing it as a speedup. If neutral,
  say so and don't commit it as one.
- For complex or speculative performance work, run a de-risk/validation
  phase first, show the results plainly regardless of outcome, and pause
  for explicit approval before continuing to implementation.

## Repo hygiene

- Gitignore `docs/superpowers/` (and any local `scratch/`) in every
  project. Brainstorming specs and execution plans are session-scoped
  scaffolding -- durable rationale belongs in commit messages, PR
  descriptions, and code comments, where it can't drift out of sync with
  the code.
