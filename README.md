# agent-config

Personal, cross-project agent configuration: canonical `AGENTS.md` of
operational preferences (workflow habits, verification philosophy,
design taste) and personal `skills/`, shared across every project via
links into each supported host's skill location.

Project-local instruction files stay in their own repos and add only
what's local to that project (build commands, architecture, domain
conventions) -- they should not repeat what's here.

## Install (new machine)

macOS and Linux:

```
git clone <remote-url> ~/Documents/Projects/agent-config
~/Documents/Projects/agent-config/install.sh
```

Windows (PowerShell):

```
git clone <remote-url> ~/Documents/Projects/agent-config
~\Documents\Projects\agent-config\install.ps1
```

Both are thin shims over `install.py`; run that directly with
`pixi run -e dev python install.py` if you prefer. One command,
deliberately: the installer writes the Claude and Codex instruction
adapters, links skills for both hosts, materializes the dev environment,
and registers Claude Code and Codex lifecycle hooks *in that order*.
Registered hooks name the dev environment's python in their command, so
registering before the environment exists writes hooks that cannot
start. The Codex registrar configures `~/.codex/hooks.json`; after
installation, review each entry and explicitly trust it through Codex
`/hooks`. Configuration is not trust, so `pixi run preflight` reports
them separately. Requires `pixi` on PATH.

No elevation and no Developer Mode is required on Windows. Skills are
linked with directory junctions rather than symlinks, since a junction
needs no privilege (`os.symlink` fails there with `WinError 1314`
without one). `~/.claude/CLAUDE.md` is an `@import` stub pointing to
this repo's `AGENTS.md`, while `~/.codex/AGENTS.md` is a generated
snapshot of it; junctions cannot span to a file. Both are handled by
`scripts/platform_paths.py`, the one place each platform difference this
repo cares about is decided.

Re-running the installer is safe -- it replaces existing links, prunes
links to skills this repo no longer has, and backs up anything real it
would otherwise overwrite, file or directory alike
(`<path>.<timestamp>.bak`, dated so that a second run cannot destroy the
first run's backup).

## Development commands

This repo is Pixi-managed like the other projects it documents. Every
project carries its own environment with a current interpreter -- never
the system `python3`, which on macOS is still 3.9 and quietly pushes
scripts and hooks into contortions for a version nobody chose.
`pixi run preflight` fails rather than warns if it is running outside a
project-local environment, or below the floor the project declares. A
project with no `pixi.toml` gets a warning instead, since these scripts
are copied into repos that manage their environments some other way. An
env reached through a symlink counts as local, which is what a git
worktree sharing the parent checkout's `.pixi` has. Only a too-old
interpreter stops the remaining checks -- the alternative was a copy of
preflight reporting one failure and inspecting nothing.

`pixi run preflight` also confirms that both instruction adapters match
the canonical guidance and that skills are linked into both host
destinations. Re-run the installer after updating this repository if it
reports an adapter or link as stale.

Hooks in `~/.claude/settings.json` must therefore name this repo's
environment python explicitly, not `python3`. The installer writes that
for you, backing the file up first, so the interpreter cannot drift by
hand.

```
pixi install -e dev                 # one-time: materialize the dev env
pixi run -e dev pre-commit install  # one-time: wire up the git hook
pixi run preflight                  # Step 0 environment check
pixi run format                     # ruff (py) + mdformat (md), autofix
pixi run lint                       # ruff check
pixi run ascii                      # scripts/check_ascii.py
pixi run spell                      # codespell
pixi run friction                   # recurring friction from transcripts
pixi run burn                       # where a session's tokens went
pixi run toolgaps                   # missing tooling + reusable assets
pixi run skills                     # validate portable Agent Skills metadata
pixi run suppressions               # every noqa must say why
pixi run thresholds                 # assertion bounds a diff loosened
pixi run audit                      # agent-asset principle breaches
                                    #   (--strict fails on warnings too)
pixi run nightly                    # gate an unattended improvement pass
pixi run test                       # pytest
pixi run precommit                  # pre-commit run --all-files
pixi run all                        # format, lint, ascii, spell,
                                    #   suppressions, thresholds,
                                    #   audit, test
```

## Codex session analytics

Codex capture is opt-in. Run `pixi run capture-codex -- <arguments>` to
execute `codex exec --json` with those arguments and save its JSONL
output under `~/.agents/analytics/codex-exec/v1/`. Analyze captured
command failures with `pixi run friction -- --source codex`. This
adapter captures only non-interactive `codex exec --json` runs and never
reads or consumes interactive Codex session state.

The v1 reader supports friction only. `pixi run burn -- --source codex`
reports that Codex cost reporting is unsupported because the capture has
no priced usage data; it never estimates a cost. Claude `burn` output
and pricing remain separate and unchanged.

## Layout

- `AGENTS.md` -- the canonical global guidance. `~/.claude/CLAUDE.md` is
  a one-line `@` import stub targeting it, and `~/.codex/AGENTS.md` is a
  generated snapshot marked with its source. Neither adapter needs a
  file link or elevated privilege.
- `docs/PORTABILITY.md` -- the boundary between the portable core and
  host-specific adapters, including the support matrix and the
  conservative Agent Skills profile enforced by `pixi run skills`.
- `skills/<name>/` -- each linked to both `~/.claude/skills/<name>/` and
  `~/.agents/skills/<name>/`: a symlink on macOS/Linux, a directory
  junction (no elevation, no Developer Mode) on Windows. `preflight`
  reports a skill this repo carries that is not linked on either host,
  and a link left behind by one that was renamed or deleted -- machine
  state, like hook registration, and the same manual step nothing
  verified. The installer writes the missing links and prunes stale ones
  in both destinations.
- `skills/standards-and-spec-review/CODING_STANDARDS.md` -- the single
  definition of the house coding rules. The canonical `AGENTS.md` names
  them as triggers and points here; nothing restates them.
- `skills/compute-job-safety/` -- interruption and restart safety for
  long-running GPU, cluster, batch, and simulation jobs. It keeps
  process identity, cleanup, and output protection mechanisms in each
  owning project rather than guessing at arbitrary running processes.
- `skills/notebooks/` -- which tool to reach for on a `.ipynb`, how to
  find the notebook MCP server that no config file lists, and why a
  measured result belongs in cell output rather than markdown prose. The
  baseline that motivated it cost 823 tool calls for one notebook.
- `skills/math/` -- state each equation's provenance unprompted, know
  what a CAS can and cannot verify about it, and derive once rather than
  twice at two rigour levels.
- `install.py` -- creates/repairs both host adapters and skill links,
  then registers the current Claude Code and Codex lifecycle hooks; the
  actual installer behind both shims below.
- `install.sh` -- POSIX shim over `install.py`, for macOS and Linux.
- `install.ps1` -- PowerShell shim over `install.py`, for Windows.
- `scripts/platform_paths.py` -- where every platform difference the
  installer, hook registration, `preflight` and the audit care about is
  decided once: the pixi interpreter layout, what counts as a link, and
  junction vs symlink. A library module, not a script -- hooks
  deliberately do not import it, since they run standalone under
  whatever interpreter `~/.claude/settings.json` names.
- `scripts/installation_contract.py` -- the shared canonical guidance,
  generated adapter formats and host destination tuples used by the
  installer and preflight. It is an import-only contract module, not a
  command.
- `hooks/` -- invoked by `~/.claude/settings.json`. Each hook declares
  its own event in a marker comment near the top
  (`# claude-hook: PostToolUse Write|Edit`) and the installer registers
  them, so adding a hook needs no manual edit and cannot silently ship
  inert. A hook may carry several markers and answer several events. A
  test fails if a hook omits its marker; `preflight` reports when this
  machine's registrations are out of date, since that is machine state
  rather than repo state and no test can gate it.
- `scripts/register_codex_hooks.py` -- converges the five supported
  policy mappings in `~/.codex/hooks.json` while preserving foreign
  handlers. It configures hooks; review and trust them through Codex
  `/hooks` before they run.
- `scripts/capture_codex_exec.py` -- opt-in capture of a
  `codex exec --json` run, as `pixi run capture-codex -- <args>`. It
  exists because the Claude readers below mine transcripts the harness
  writes on its own, and Codex leaves no equivalent on disk: without a
  capture step there is nothing for `friction.py` to read. It wraps only
  non-interactive `codex exec` and never touches interactive session
  state, and it stores each run under a versioned directory
  (`~/.agents/analytics/codex-exec/v1/`) whose version names the reader
  contract, so a format change is a new directory rather than a silently
  misparsed one.
- `scripts/burn.py` -- where a session's tokens actually went, as
  `pixi run burn`. The companion to `friction.py`, and the same shape:
  it reads the transcripts off disk, so observing costs no model
  context, and it always exits 0 because a report is not a gate. It
  exists because this repo measured everything except the bill --
  `friction.py` counts recurring *errors* and `audit_assets.py` bounds
  *static* always-loaded prose, and neither can see the dominant cost,
  which is dynamic: cache reads -- the conversation being re-sent every
  turn -- were 61% of orchestrator spend in the first month measured
  this way, and the mean cost of a turn rose 2.7x between a session's
  first decile and its last. It prices subagent transcripts too (they
  are nested under `<session>/subagents/`, and a top-level-only sweep
  made delegation look free -- they were 23% of spend). Two of its
  numbers are regression signals for changes already made:
  `dispatches_missing_model` should stay at 0 while
  `hooks/agent-model.py` is registered, and review rounds per session
  should fall from the 3-5 seen before step 6 was scoped to the fix
  diff. The `PRICING` table is the one thing that can go stale and still
  produce confident output, so the rates travel with every report. It
  reports the *shape* of read-only output as well as its share --
  median, p90, p99, the largest calls by name, and the fraction of read
  chars coming from results at or over `OVERSIZED_CHARS` -- because the
  share alone cannot say whether a check at the call site would pay for
  itself or just be friction, and that is the evidence a tier-1 decision
  needs. The first run's answer, recorded in the docstring, was that it
  would not: the largest reads wanted the file contents they fetched, so
  a check there redirects the cost instead of removing it.
- `scripts/nightly.py` -- the gate on an unattended improvement pass, as
  `pixi run nightly`. It runs `friction`, `audit --strict` and
  `toolgaps`, none of which spend model context, and exits without
  staging anything unless one crossed a bar it already owned. When one
  did, it writes `.nightly-brief` naming what and stops: a model reads
  that brief in a fresh session, runs `reflect`, and proposes a diff on
  a branch that a human merges or discards. It will not stage a second
  brief while the first is unread, and it fails loudly rather than
  reading a crashed instrument as silence. The gate is the artifact --
  asked what was frustrating, a model always answers, and SkillOpt
  measured an ungated version of this loop falling from 0.554 to 0.026
  over five nights while its gated twin lost nothing.
- `friction-ledger.toml` -- decisions about recurring friction found by
  `pixi run friction`, each recording a `cause` as well as an `outcome`.
  A decided class is not re-proposed unless its count doubles, which is
  what makes the improvement loop converge rather than nag.
- Each context budget has two bands. Crossing the lower one prints a
  warning, exits 0, and asks the three questions the `reflect` skill
  owns -- is this duplicated prose or duplicated intent, does it add
  context or reinforce decaying behaviour or neither, does it belong in
  a lower tier. Crossing the upper one fails. Warnings are deliberately
  not ledgerable: an exception suppresses a finding until the asset
  changes, which is right for a decision made once and wrong for a
  question whose answer changes as the asset grows. `--strict` promotes
  warnings to failures, for an unsupervised run that has no human to
  ask.
- `audit-ledger.toml` -- accepted exceptions to the five agent-asset
  principles, keyed on asset *and* principle. Where `friction-ledger`
  reopens a class when its count doubles, an entry here carries the
  audited file's `asset_sha` and expires when that file changes: a
  friction is an event stream, but an audit finding is a statement about
  a file, so a decision about a file is only valid for the file it was
  made about. `pixi run audit --sha <asset>` gives the value, so writing
  an entry never means opening the script. An exception whose asset the
  current branch has edited reports as *awaiting re-grant* rather than
  as a failure, so the re-grant is due once, at branch end, against the
  asset's final state -- charging one per commit re-judged an asset
  about to change again, and left the note narrating its own drafts. The
  grace needs a prior accepted exception, so a new violation still
  fails, and it evaporates on the default branch.
- `skills/reflect/` -- diagnoses *why* a friction recurs before deciding
  what to change, and prefers a hook over a script over a skill over
  prose, because a hook does not gate on context.
- `skills/config-audit/` -- audits the assembled config against five
  agent-asset principles, which `AGENT_ASSET_PRINCIPLES.md` defines on
  demand in the same arrangement as `CODING_STANDARDS.md`. The boundary
  against `reflect` is one sentence: reflect asks why something went
  wrong, this asks whether the system as assembled is still worth what
  it costs, so it needs no incident to run. It consumes
  `pixi run audit --json` rather than re-reading every asset, and it is
  forbidden from proposing new skills -- `reflect` owns the tier ladder,
  and without that boundary an auditing skill becomes the skill factory
  reflect exists to prevent.
- `skills/writing-orchestration/` -- the prose counterpart to
  `workflow-orchestration`. The split is one sentence:
  `workflow-orchestration` owns deliverables whose correctness a test
  asserts, this one owns deliverables whose correctness a reader judges.
  It substitutes into the shared spine rather than restating it, so the
  two cannot drift, and it says explicitly that classification picks the
  spine and not the toolbox -- otherwise a bifurcation becomes two
  silos.
- `skills/humanizer/` -- removes AI writing patterns without changing
  what the text says. `patterns.md` holds the 35-pattern catalog and is
  read on demand, because the process is what gets internalized while
  the catalog is consulted while editing. That file is also the one
  place a `check-ascii: allow` marker is used: patterns 14, 18 and 19
  are about the shape of the characters themselves, so the examples have
  to contain them.
- `hooks/prose-writing.py` -- fires once per session per project when a
  prose file is about to be written, because the task rarely announces
  itself as writing ("tighten section 3") and the coding spine is what
  gets reached for otherwise.
- `hooks/promotion-check.py` -- fires when an `AGENTS.md`, `CLAUDE.md`,
  memory or skill file is written *outside* this repo, asking whether
  the preference is general enough to belong here instead. It resolves
  links before matching, because the installer links this repo into
  `~/.claude`, so editing the config through its installed path would
  otherwise look like editing a foreign project and the hook would tell
  you to promote a file you are already editing here.
- `hooks/task-list.py` -- injects the project's actual short-form task
  commands at session start. It replaced a rule that said "use the
  project's task commands" with the information that rule was a proxy
  for: the observed failure was not ignorance of the rule but not
  knowing that `pixi run format` existed and covered the work. It parses
  the manifest with a regex rather than `tomllib`, because the
  interpreter that runs a hook is named in `~/.claude/settings.json` --
  a file outside this repo's checks -- and a task list is worth having
  approximately when that file is stale.
- `skills/quantikz/` -- drawing and debugging quantum circuit diagrams
  in LaTeX. The one domain skill here rather than a workflow one, and
  the reason `.pre-commit-config.yaml` excludes its directory from
  `mdformat`: the reference material is full of bare backslashes, and
  the formatter turns `\gate` into `\\gate`.
- `hooks/audit-owed.py` -- on a commit touching `skills/`, `scripts/`,
  `hooks/` or `AGENTS.md`, records the asset in a gitignored
  `.audit-owed` and asks for *one* audit at branch end rather than one
  per commit -- an audit that fired on all eight commits of a branch
  would report the same findings eight times and get skimmed by the
  fourth. A marker file rather than a message because context is lost to
  compaction and session end, and `preflight` reads the marker, so a
  fresh session picks up an audit an earlier one owed, and
  `pixi run audit --clear-owed` is what ends it -- by stamping each
  obligation with the hash it was discharged against rather than
  deleting it, so an audit run too early re-opens by itself when the
  asset next changes. `AGENT_CONFIG_REPO` overrides the install path for
  a clone kept elsewhere (`CLAUDE_CONFIG_REPO` is still honored, so an
  override predating the rename keeps working).
- `hooks/agent-model.py` -- denies an `Agent` dispatch that omits
  `model` when the agent type is a catch-all (`general-purpose`,
  `claude`, or absent), because those inherit the session model and this
  config runs Opus. AGENTS.md already asks for the cheapest model that
  holds accuracy, but the harness default fights the rule: the only way
  to miss it is upward, and forgetting the field costs the most a
  dispatch can cost. Measured over 30 days, 19 of 163 dispatches omitted
  it, and one session omitted it on all 10 of its own. It denies rather
  than advises because an advisory is a second request to behave and the
  first one was already being ignored; `opus` stays a valid answer, it
  just has to be typed. Named specialists and `fork` are left alone -- a
  specialist may pin its own model, and `fork` ignores the override.
- `hooks/notify.py` -- plays a sound and posts a desktop banner when the
  turn genuinely comes back to you: the work finished (`Stop`), a tool
  wants permission or a background agent is blocked on an answer
  (`Notification`), or Claude is asking a question (`AskUserQuestion`).
  "Finished" is the load-bearing word. `Stop` also fires each time the
  main loop yields to wait on a background subagent, which in an
  orchestrated task is once per subagent round-trip; the hook tells the
  two apart by the `background_tasks` the host puts in the payload for
  exactly this purpose, and stays quiet while any are in flight. A
  prompt merely sitting idle is not announced at all, since the turn
  that left it open was announced when it ended. That gate is unbounded
  -- a task that never finishes would hold the ping for as long as it
  runs -- so a parked turn also spawns a detached watchdog that says
  once, after ten minutes, that background work is still holding the
  ping and may be stuck. A reactive check could not do that job: a
  wedged task produces no events, so the hook is never invoked in the
  one case worth catching. One nudge per continuous in-flight stretch --
  the clock is a marker file, in a private per-user directory, armed on
  the first parked turn and released only when the work drains, so a
  later long stretch gets its own and the current one cannot nag twice.
  Sounds are a table at the top of the file, so they are
  version-controlled and a new machine sounds like this one;
  `CLAUDE_NOTIFY_OFF=1 claude` mutes a single session,
  `CLAUDE_NOTIFY_SOUND_DONE=Tink` overrides one reason and
  `CLAUDE_NOTIFY_LONG_SECONDS=60` tightens the stalled-work nudge.
  Terminal-agnostic because the sound comes from the OS rather than a
  BEL written to a tty, so a bare terminal, the VSCode integrated
  terminal and tmux all behave alike. It replaces the
  `singularityinc.claude-notifier` VSCode extension, which did the same
  job but kept its sounds in a machine-local file the installer knows
  nothing about -- so a new machine came up silent until someone
  remembered an extension. On macOS the banner is posted by
  `terminal-notifier` when it is installed and by `osascript` otherwise;
  the `osascript` path is attributed to Script Editor and is dropped
  silently if that app has no notification permission, so
  `brew install terminal-notifier` is the fix for a missing banner.
- `scripts/` -- generic CD tools (`check_ascii.py`, `preflight.py`,
  `friction.py`, `burn.py`, `toolgaps.py`, `validate_skills.py`,
  `suppressions.py`, `thresholds.py`) meant to be copied into new
  projects rather than rewritten from scratch. Copied alone each one
  runs; `preflight.py` skips its two link-related checks unless
  `platform_paths.py` is copied beside it, and says so rather than
  failing to start. Plus `register_hooks.py` and `audit_assets.py`,
  which are specific to this repo -- the first to its install, the
  second because it knows this layout rather than describing a
  capability every project has. `audit_assets.py` also owns the
  always-loaded context ceilings, which `tests/test_context_budget.py`
  imports rather than restating, so the gate and the report share one
  definition of each number. `check_ascii.py` lets a single file opt out
  with a reason-bearing `check-ascii: allow` marker in its first ten
  lines; a marker with no reason fails rather than skipping, so the
  exemption is documented rather than silent.
- `.mdformat.toml` -- Markdown formatter settings. The plugin list is
  duplicated in `.pre-commit-config.yaml` because pre-commit builds the
  hook its own environment; both are required, and dropping either
  corrupts skill frontmatter or GFM tables.
- `docs/superpowers/` -- brainstorming specs and plans for this repo's
  own evolution (gitignored, local-only).
