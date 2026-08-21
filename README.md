# claude-config

Personal, cross-project Claude Code configuration: a master `CLAUDE.md`
of operational preferences (workflow habits, verification philosophy,
design taste) and personal `skills/`, shared across every project via
symlinks into `~/.claude/`.

Project-specific `CLAUDE.md` files stay in their own repos and add only
what's local to that project (build commands, architecture, domain
conventions) -- they should not repeat what's here.

## Install (new machine)

```
git clone <remote-url> ~/Documents/Projects/claude-config
~/Documents/Projects/claude-config/install.sh
```

One command, deliberately. `install.sh` links the config, materializes
the dev environment, and registers the hooks *in that order* --
registered hooks name `.pixi/envs/dev/bin/python` in their command, so
registering before the environment exists writes hooks that cannot
start. Requires `pixi` on PATH.

Re-running `install.sh` is safe -- it replaces existing symlinks and
backs up any real file it would otherwise overwrite (`<path>.bak`).

## Development commands

This repo is Pixi-managed like the other projects it documents. Every
project carries its own environment with a current interpreter -- never
the system `python3`, which on macOS is still 3.9 and quietly pushes
scripts and hooks into contortions for a version nobody chose.
`pixi run preflight` fails rather than warns if it is running outside a
project-local environment, or below the floor the project declares.

Hooks in `~/.claude/settings.json` must therefore name this repo's
environment python explicitly, not `python3`. `./install.sh` writes that
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
pixi run toolgaps                   # missing tooling + reusable assets
pixi run suppressions               # every noqa must say why
pixi run thresholds                 # assertion bounds a diff loosened
pixi run audit                      # agent-asset principle breaches
pixi run test                       # pytest
pixi run precommit                  # pre-commit run --all-files
pixi run all                        # format, lint, ascii, spell,
                                    #   suppressions, audit, test
```

## Layout

- `CLAUDE.md` -- symlinked to `~/.claude/CLAUDE.md`, loaded in every
  Claude Code session.
- `skills/<name>/` -- each symlinked to `~/.claude/skills/<name>/`.
- `skills/standards-and-spec-review/CODING_STANDARDS.md` -- the single
  definition of the house coding rules. The master `CLAUDE.md` names
  them as triggers and points here; nothing restates them.
- `install.sh` -- creates/repairs the symlinks above and registers
  hooks.
- `hooks/` -- invoked by `~/.claude/settings.json`. Each hook declares
  its own event in a marker comment near the top
  (`# claude-hook: PostToolUse Write|Edit`) and `./install.sh` registers
  them, so adding a hook needs no manual edit and cannot silently ship
  inert. A hook may carry several markers and answer several events. A
  test fails if a hook omits its marker; `preflight` reports when this
  machine's registrations are out of date, since that is machine state
  rather than repo state and no test can gate it.
- `friction-ledger.toml` -- decisions about recurring friction found by
  `pixi run friction`, each recording a `cause` as well as an `outcome`.
  A decided class is not re-proposed unless its count doubles, which is
  what makes the improvement loop converge rather than nag.
- `audit-ledger.toml` -- accepted exceptions to the five agent-asset
  principles, keyed on asset *and* principle. Where `friction-ledger`
  reopens a class when its count doubles, an entry here carries the
  audited file's `asset_sha` and expires when that file changes: a
  friction is an event stream, but an audit finding is a statement about
  a file, so a decision about a file is only valid for the file it was
  made about. `pixi run audit --sha <asset>` gives the value, so writing
  an entry never means opening the script.
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
- `hooks/audit-owed.py` -- on a commit touching `skills/`, `scripts/`,
  `hooks/` or `CLAUDE.md`, records the asset in a gitignored
  `.audit-owed` and asks for *one* audit at branch end rather than one
  per commit -- an audit that fired on all eight commits of a branch
  would report the same findings eight times and get skimmed by the
  fourth. A marker file rather than a message because context is lost to
  compaction and session end, and `preflight` reads the marker, so a
  fresh session picks up an audit an earlier one owed, and
  `pixi run audit --clear-owed` is what ends it. `CLAUDE_CONFIG_REPO`
  overrides the install path for a clone kept elsewhere.
- `hooks/notify.py` -- plays a sound and posts a desktop banner when the
  turn comes back to you: the turn ended (`Stop`), a tool wants
  permission or the prompt has gone idle (`Notification`), or Claude is
  asking a question (`AskUserQuestion`). Sounds are a table at the top
  of the file, so they are version-controlled and a new machine sounds
  like this one; `CLAUDE_NOTIFY_OFF=1 claude` mutes a single session and
  `CLAUDE_NOTIFY_SOUND_DONE=Tink` overrides one reason.
  Terminal-agnostic because the sound comes from the OS rather than a
  BEL written to a tty, so a bare terminal, the VSCode integrated
  terminal and tmux all behave alike. It replaces the
  `singularityinc.claude-notifier` VSCode extension, which did the same
  job but kept its sounds in a machine-local file `install.sh` knows
  nothing about -- so a new machine came up silent until someone
  remembered an extension. On macOS the banner is posted by
  `terminal-notifier` when it is installed and by `osascript` otherwise;
  the `osascript` path is attributed to Script Editor and is dropped
  silently if that app has no notification permission, so
  `brew install terminal-notifier` is the fix for a missing banner.
- `scripts/` -- generic CD tools (`check_ascii.py`, `preflight.py`,
  `friction.py`, `toolgaps.py`, `suppressions.py`, `thresholds.py`)
  meant to be copied into new projects rather than rewritten from
  scratch, plus `register_hooks.py` and `audit_assets.py`, which are
  specific to this repo -- the first to its install, the second because
  it knows this layout rather than describing a capability every project
  has. `audit_assets.py` also owns the always-loaded context ceilings,
  which `tests/test_context_budget.py` imports rather than restating, so
  the gate and the report share one definition of each number.
  `check_ascii.py` lets a single file opt out with a reason-bearing
  `check-ascii: allow` marker in its first ten lines; a marker with no
  reason fails rather than skipping, so the exemption is documented
  rather than silent.
- `.mdformat.toml` -- Markdown formatter settings. The plugin list is
  duplicated in `.pre-commit-config.yaml` because pre-commit builds the
  hook its own environment; both are required, and dropping either
  corrupts skill frontmatter or GFM tables.
- `docs/superpowers/` -- brainstorming specs and plans for this repo's
  own evolution (gitignored, local-only).
