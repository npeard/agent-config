# agent-config

Working habits, skills and guard-rail hooks for Claude Code and Codex,
tuned for research software: Python under Pixi, GPU and cluster jobs,
notebooks, and papers in LaTeX or Typst. Install it once and every
project on the machine shares it.

It lets you hand a coding agent a whole task -- from spec to merged
branch -- and be interrupted twice, while hooks block the habits that
waste the most time and money.

## What you get

- **Hand off a whole task.** The agent follows one sequence --
  understand, specify, branch, implement with subagents, verify, review,
  integrate -- built on
  [superpowers](https://github.com/obra/superpowers). It stops for you
  at the finished spec and at the final report, and works on its own in
  between. Papers and thesis chapters run the same sequence, with a
  reader rather than a test as the judge.
- **Hooks for the expensive mistakes.** An instruction in a prompt can
  be ignored; a hook cannot. One refuses a subagent dispatch that names
  no model, so a delegated search never silently runs on the most
  expensive one. Two more stop a subagent from sleep-polling a long job
  and stop a session from resuming a subagent whose context is already
  huge. In the session that prompted them, sleep-polling caused 95% of
  the tokens written to the prompt cache, and one resume re-sent over
  700k tokens.
- **It measures itself.** `pixi run burn` reads session transcripts off
  disk and reports where the tokens and dollars went;
  `pixi run friction` finds failures that keep recurring. Neither spends
  any model context. The first cost report found that cache reads -- the
  conversation re-sent every turn -- were 61% of the main session's
  spend.
- **Writing help that checks as well as advises.** Skills cover
  scientific papers, talks and thesis chapters, equations, Typst, and
  removing AI-sounding prose. After each LaTeX or Typst edit a hook
  reports sentence length and forward references, and another blocks
  plain-text math such as `3pi/2` in a figure label.
- **Know-how for research code.** Stopping and restarting long GPU jobs
  without orphaned processes or overwritten results, keeping a session
  to its share of the machine, and editing notebooks reliably -- the
  baseline that prompted that skill took 823 tool calls for one
  notebook.
- **You hear when it needs you.** A sound and a desktop notification
  when the work finishes or a tool needs permission, once per task
  rather than once per subagent, on macOS, Linux and Windows.
- **Checks for your other projects, with no install.** The commit-time
  checks this repo runs on itself -- non-ASCII characters, plain-text
  math, functions too thin to exist -- are published as pre-commit hooks
  any project can pin by version.

## Install

You need [Pixi](https://pixi.sh),
[Claude Code](https://claude.com/claude-code) or Codex, and the
superpowers plugin, which the workflow names at every step. In Claude
Code:

```
/plugin install superpowers@claude-plugins-official
```

The `code-review` plugin from the same marketplace is recommended for
the review step.

Then clone the repo and run the installer. macOS and Linux:

```
git clone https://github.com/npeard/agent-config.git
agent-config/install.sh
```

Windows (PowerShell, no administrator rights needed):

```
git clone https://github.com/npeard/agent-config.git
agent-config\install.ps1
```

To update, `git pull` and run the installer again. `pixi run preflight`
reports anything the installer left stale.

### What the installer changes

Read this before installing over an existing setup:

- `~/.claude/CLAUDE.md` becomes a one-line import of this repo's
  `AGENTS.md`, and `~/.codex/AGENTS.md` a generated copy of it. Your own
  global instructions there are moved to `<file>.<timestamp>.bak` and no
  longer load, so fold what you want to keep into your fork's
  `AGENTS.md`.
- Each skill is linked into `~/.claude/skills/` and `~/.agents/skills/`.
  Skills already there are left alone.
- Hooks are added to `~/.claude/settings.json`, backed up first, and to
  `~/.codex/hooks.json`. Codex runs a hook only after you trust it
  through Codex `/hooks`.

To see the result without touching your real config:

```
pixi run -e dev python install.py --home /tmp/trial-home --skip-env
```

### Make it your own

This config encodes one person's preferences, so fork it rather than
installing it unchanged. The parts most likely to need editing:

- `AGENTS.md` -- the always-loaded guidance, including when the agent
  may stop and ask you.
- `vscode-extensions.toml` -- one machine's required and forbidden VS
  Code extensions, checked at every session start. Edit it or empty it.
- `hooks/agent-model.py` -- the hook that makes every subagent dispatch
  name a model.
- `hooks/notify.py` -- the sounds. `CLAUDE_NOTIFY_OFF=1` mutes it.

## Use the gates in another project

A gate is a check that fails a commit. These need neither the installer
above nor Pixi: pre-commit fetches them itself. Pin a release tag rather
than copying a script, since a copy stops getting fixes; nothing changes
in a project until you move its tag.

Add this repo to the project's `.pre-commit-config.yaml`, listing any of
the hooks in the table below, then run `pre-commit install` once:

```yaml
repos:
  - repo: https://github.com/npeard/agent-config
    rev: v0.1.0
    hooks:
      - id: check-ascii
      - id: plain-math
        files: '(\.typ|(?<!\.code)\.tex|/(figures|plots?)/[^/]*\.py)$'
```

| Hook               | Fails on                                                                 |
| ------------------ | ------------------------------------------------------------------------ |
| `check-ascii`      | Any non-ASCII character in Python or Markdown                            |
| `plain-math`       | Plain-text math (`alpha`, `x^2`) in plot labels and documents            |
| `trivial-wrappers` | Python functions too thin to justify existing                            |
| `forward-refs`     | A LaTeX or Typst document citing a label before the label appears        |
| `report-check`     | A report whose figure list disagrees with its document or figure scripts |

Narrow a hook with `files:` or `exclude:` in the project's own config.

For the commands you run yourself, add a Pixi git dependency on the same
tag. In `pyproject.toml` (in a `pixi.toml`, the table is
`[pypi-dependencies]`):

```toml
[tool.pixi.pypi-dependencies]
agent-config = { git = "https://github.com/npeard/agent-config", tag = "v0.1.0" }
```

That installs the five gates above as commands, plus

- `preflight` -- checks the project is fit to start work in: pre-commit
  installed, tests green, default branch, clean tree.
- `new-report REPORT_DIR --shared SHARED_DIR --title TITLE` -- scaffolds
  a report whose figures are built from saved results.
- `jupyter-mcp --port PORT --token TOKEN --timeout SECONDS --root DIR`
  -- starts JupyterLab and prints the `claude mcp add` command that
  connects Claude Code to it.

Every command takes `--help`. Its name and options are the compatibility
promise; anything else in `scripts/` may change between versions. To
upgrade, run
`pre-commit autoupdate --repo https://github.com/npeard/agent-config`
and set the Pixi `tag` to match.

To move a project off copied scripts: delete the copies, replace the
local hooks that ran them with the hooks above (keeping their `files:`),
point Pixi tasks at the commands, and run `pre-commit run --all-files`.
Expect new findings the first time, since the current tools check more
than old copies did.

## Contributing

```
pixi install -e dev
pixi run -e dev pre-commit install
pixi run all          # format, lint, spelling, audit, tests and more
```

`pixi task list` shows the rest. Two rules shape most changes here.
Prefer the cheapest tool that fixes a problem -- nothing, then a hook,
then a script, then a skill, and a rule in `AGENTS.md` last, because
every session pays to read that file. And a change to a skill, hook or
script is checked as part of the whole set: `pixi run audit` reports
breaches of the five principles in
`skills/config-audit/AGENT_ASSET_PRINCIPLES.md`.

[docs/LAYOUT.md](docs/LAYOUT.md) covers how the installer works and
lists every file with the reason it exists.
[docs/PORTABILITY.md](docs/PORTABILITY.md) separates the portable core
from the Claude Code and Codex adapters.

To release, set `version` in `pyproject.toml`, merge to `main`, tag that
commit `vX.Y.Z` to match, and push the tag. Never move a tag once
pushed: projects pin it.

## License

MIT; see `LICENSE`. `skills/humanizer/` is adapted from
[blader/humanizer](https://github.com/blader/humanizer) and carries its
own MIT notice in `skills/humanizer/LICENSE`.
