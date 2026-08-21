#!/usr/bin/env python3
# claude-hook: PostToolUse Bash
"""Record that a config audit is owed, so the obligation outlives the session.

A per-commit audit was the obvious design and the wrong one. friction-ledger
exists because a loop that fires every time gets skimmed, and an audit that
ran on all eight commits of a branch would report the same nine findings
eight times. So this notices every commit and asks for one audit, at the end.

The marker file rather than a message is the point. A reminder in context is
lost to compaction, to session end, or to a fresh checkout of the branch; a
file on disk is still there tomorrow, and preflight reports it to whichever
session comes next.

Scoped to this repo. Auditing an arbitrary project's config is a different
job with different principles, and promotion-check.py already covers the
"you wrote a skill somewhere else" case.
"""

import json
import os
import subprocess
import sys


def master_repo() -> str:
    """Where this config lives, resolved.

    CLAUDE_CONFIG_REPO wins when set. The default is the path the README's
    install instructions use, but hardcoding only that makes the hook dead
    for anyone who cloned elsewhere -- and makes a test's HOME patch the only
    way to point it somewhere else, which is an unreliable thing to depend on.
    """
    override = os.environ.get("CLAUDE_CONFIG_REPO")
    root = override or os.path.expanduser("~/Documents/Projects/claude-config")
    return os.path.realpath(root)


MARKER = ".audit-owed"
CONFIG_PREFIXES = ("skills/", "scripts/", "hooks/")
CONFIG_FILES = ("CLAUDE.md",)


def is_config_asset(path: str) -> bool:
    return path.startswith(CONFIG_PREFIXES) or path in CONFIG_FILES


def failed(response) -> bool:
    """True only when the response positively says the command failed.

    Deliberately one-directional: an unrecognised payload shape means "not
    known to have failed", so a schema change degrades to the previous
    behaviour rather than silencing the hook entirely.
    """
    if not isinstance(response, dict):
        return False
    if response.get("is_error") or response.get("interrupted"):
        return True
    for key in ("exit_code", "exitCode", "returncode", "returnCode"):
        code = response.get(key)
        if isinstance(code, int) and code != 0:
            return True
    return False


def committed_paths(repo: str) -> list[str]:
    """Paths in HEAD's commit.

    PostToolUse means the commit already happened, so the staged set is gone
    and HEAD is what was recorded. Failures return empty rather than raising:
    a hook that tracebacks is noisier than one that declines. `git commit`
    appearing in a command is not proof a commit succeeded either; `failed`
    above is what guards that, since HEAD would otherwise be the *previous*
    commit.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                repo,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                # --root: a parentless commit otherwise reports no paths at
                # all. -m: nor does a merge commit, and a merge is how config
                # assets usually arrive on the default branch.
                "--root",
                "-m",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> None:
    repo = master_repo()
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # Malformed or empty stdin: promotion-check.py guards the identical
        # call for the same reason.
        return
    if not isinstance(data, dict):
        return

    command = (data.get("tool_input") or {}).get("command") or ""
    if "git commit" not in command:
        return

    if failed(data.get("tool_response")):
        # This repo runs ruff with --exit-non-zero-on-fix, so a rejected then
        # retried commit is routine. Without this the hook reads the *previous*
        # commit and claims one just happened.
        return

    cwd = data.get("cwd")
    if not cwd:
        return
    # Realpath before comparing: install.sh symlinks this repo into
    # ~/.claude, so a session can hold a path that resolves here without
    # looking like it. The trailing separator stops a bare prefix test from
    # also swallowing a sibling like "claude-config-other".
    resolved = os.path.realpath(cwd)
    if resolved != repo and not resolved.startswith(repo + os.sep):
        return

    touched = {p for p in committed_paths(repo) if is_config_asset(p)}
    if not touched:
        return

    marker = os.path.join(repo, MARKER)
    try:
        with open(marker) as fh:
            known = {line.strip() for line in fh if line.strip()}
    except OSError:
        known = set()

    if touched <= known:
        # Already owed for these assets. Asking again on every later commit is
        # the nagging this design exists to avoid.
        return

    known |= touched
    try:
        with open(marker, "w") as fh:
            fh.write("\n".join(sorted(known)) + "\n")
    except OSError:
        # Cannot record it, so do not claim it was recorded.
        return

    listed = ", ".join(sorted(touched)[:4])
    more = ", ..." if len(touched) > 4 else ""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"This branch has changed {len(known)} claude-config "
                        f"asset(s) ({listed}{more}). Before integrating, run "
                        "`pixi run audit` and invoke the config-audit skill "
                        "once -- not once per commit, then "
                        "`pixi run audit --clear-owed`."
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
