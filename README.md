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
pixi run test                       # pytest
pixi run precommit                  # pre-commit run --all-files
pixi run all                        # format, lint, ascii, spell,
                                    #   suppressions, test
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
  inert. A test fails if a hook omits its marker; `preflight` reports
  when this machine's registrations are out of date, since that is
  machine state rather than repo state and no test can gate it.
- `friction-ledger.toml` -- decisions about recurring friction found by
  `pixi run friction`, each recording a `cause` as well as an `outcome`.
  A decided class is not re-proposed unless its count doubles, which is
  what makes the improvement loop converge rather than nag.
- `skills/reflect/` -- diagnoses *why* a friction recurs before deciding
  what to change, and prefers a hook over a script over a skill over
  prose, because a hook does not gate on context.
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
- `scripts/` -- generic CD tools (`check_ascii.py`, `preflight.py`,
  `friction.py`, `toolgaps.py`, `suppressions.py`, `thresholds.py`)
  meant to be copied into new projects rather than rewritten from
  scratch, plus `register_hooks.py`, which is specific to this repo's
  install. `check_ascii.py` lets a single file opt out with a
  reason-bearing `check-ascii: allow` marker in its first ten lines; a
  marker with no reason fails rather than skipping, so the exemption is
  documented rather than silent.
- `.mdformat.toml` -- Markdown formatter settings. The plugin list is
  duplicated in `.pre-commit-config.yaml` because pre-commit builds the
  hook its own environment; both are required, and dropping either
  corrupts skill frontmatter or GFM tables.
- `docs/superpowers/` -- brainstorming specs and plans for this repo's
  own evolution (gitignored, local-only).
