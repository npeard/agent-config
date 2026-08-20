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
    echo "Backing up existing $dest to $dest.bak"
    mv "$dest" "$dest.bak"
  fi
  ln -s "$src" "$dest"
  echo "Linked $dest -> $src"
}

link "$REPO_DIR/CLAUDE.md" "$CLAUDE_DIR/CLAUDE.md"

mkdir -p "$CLAUDE_DIR/skills"
for skill_dir in "$REPO_DIR"/skills/*/; do
  name="$(basename "$skill_dir")"
  link "${skill_dir%/}" "$CLAUDE_DIR/skills/$name"
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
