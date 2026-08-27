#!/usr/bin/env bash
# Installs claude-config into ~/.claude via symlinks. Safe to re-run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

link() {
  local src="$1" dest="$2"
  if [ -L "$dest" ]; then
    rm "$dest"
  elif [ -e "$dest" ]; then
    # Dated, not a fixed `.bak`: with one name a second run destroyed the only
    # copy of what the first run replaced, and ~/.claude had already lost
    # three generations of settings backups that way. The serial covers two
    # runs inside one second, which is what a test does.
    local stamp backup serial=0
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="$dest.$stamp.bak"
    while [ -e "$backup" ]; do
      serial=$((serial + 1))
      backup="$dest.$stamp-$serial.bak"
    done
    echo "Backing up existing $dest to $backup"
    mv "$dest" "$backup"
  fi
  ln -s "$src" "$dest"
  echo "Linked $dest -> $src"
}

# Created before the first link, not between the links: on a genuinely new
# machine neither directory exists, and under `set -e` the first `ln` died
# there -- so the one documented install path aborted before it materialized
# the environment or registered a single hook.
mkdir -p "$CLAUDE_DIR/skills"

link "$REPO_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"

for skill_dir in "$REPO_DIR"/skills/*/; do
  name="$(basename "$skill_dir")"
  link "${skill_dir%/}" "$CLAUDE_DIR/skills/$name"
done

# A renamed or deleted skill leaves its symlink behind, and a stale link in
# ~/.claude/skills is offered to every session as a real skill. Only links
# into this repo's skills/ are pruned: another tool's links, and a link from
# a clone kept elsewhere, are not ours to remove.
for installed in "$CLAUDE_DIR"/skills/*; do
  [ -L "$installed" ] || continue
  target="$(readlink "$installed")"
  case "$target" in
    "$REPO_DIR"/skills/*)
      if [ ! -e "$target" ]; then
        rm "$installed"
        echo "Pruned $installed -> $target (skill no longer exists)"
      fi
      ;;
  esac
done

# The dev environment is materialized before hooks are registered, not after.
# Registered hooks name `.pixi/envs/dev/bin/python` in their command, so that
# interpreter is a prerequisite for them to run at all -- registering first
# and installing later wrote two hooks pointing at a binary that did not
# exist and reported success, which is how a "new machine" install produced
# silently dead hooks.
if ! command -v pixi >/dev/null 2>&1; then
  echo "error: pixi is not on PATH. This repo is pixi-managed; install pixi" >&2
  echo "       from https://pixi.sh and re-run." >&2
  exit 1
fi

echo "Materializing dev environment (pixi install -e dev)..."
pixi install -e dev --manifest-path "$REPO_DIR/pixi.toml"

PY_BIN="$REPO_DIR/.pixi/envs/dev/bin/python"
if [ ! -x "$PY_BIN" ]; then
  echo "error: expected $PY_BIN after pixi install; aborting rather than" >&2
  echo "       registering hooks that cannot start." >&2
  exit 1
fi

# Registration is automatic because a manual step nothing verifies is a step
# that eventually gets skipped -- which is how task-list.py came to be
# written, tested, documented as registered, and never wired up. The script
# is idempotent and backs settings.json up before its first write.
"$PY_BIN" "$REPO_DIR/scripts/register_hooks.py"
