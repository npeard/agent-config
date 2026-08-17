# claude-config

Personal, cross-project Claude Code configuration: a master `CLAUDE.md` of
operational preferences (workflow habits, verification philosophy, design
taste) and personal `skills/`, shared across every project via symlinks
into `~/.claude/`.

Project-specific `CLAUDE.md` files stay in their own repos and add only
what's local to that project (build commands, architecture, domain
conventions) -- they should not repeat what's here.

## Install (new machine)

    git clone <remote-url> ~/Documents/Projects/claude-config
    ~/Documents/Projects/claude-config/install.sh

Re-running `install.sh` is safe -- it replaces existing symlinks and
backs up any real file it would otherwise overwrite (`<path>.bak`).

## Development commands

This repo is Pixi-managed like the other projects it documents:

    pixi install -e dev                 # one-time: materialize the dev env
    pixi run -e dev pre-commit install  # one-time: wire up the git hook
    pixi run format                     # ruff format + autofix
    pixi run lint                       # ruff check
    pixi run ascii                      # scripts/check_ascii.py
    pixi run spell                      # codespell
    pixi run precommit                  # pre-commit run --all-files
    pixi run all                        # format + lint + ascii

## Layout

- `CLAUDE.md` -- symlinked to `~/.claude/CLAUDE.md`, loaded in every
  Claude Code session.
- `skills/<name>/` -- each symlinked to `~/.claude/skills/<name>/`.
- `install.sh` -- creates/repairs the symlinks above.
- `hooks/` -- scripts invoked by `~/.claude/settings.json` hooks (see
  `hooks/promotion-check.py`).
- `scripts/` -- generic CD tools (e.g. `check_ascii.py`) meant to be
  copied into new projects rather than rewritten from scratch.
- `docs/superpowers/` -- brainstorming specs and plans for this repo's
  own evolution (gitignored, local-only).
