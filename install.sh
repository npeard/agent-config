#!/usr/bin/env bash
# Thin shim. The installer itself is install.py, so that one implementation
# serves every shell on every platform; see docs in that file.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v pixi >/dev/null 2>&1; then
  exec pixi run --manifest-path "$REPO_DIR/pixi.toml" -e dev python "$REPO_DIR/install.py" "$@"
fi
echo "error: pixi is not on PATH. This repo is pixi-managed; install pixi" >&2
echo "       from https://pixi.sh and re-run." >&2
exit 1
