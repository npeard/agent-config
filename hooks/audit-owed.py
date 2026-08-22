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
    # expanduser wraps the whole expression: applied only to the default, a
    # CLAUDE_CONFIG_REPO of "~/Documents/Projects/claude-config" -- the form the
    # README's own install path invites -- resolves to a literal "~" directory
    # and the hook silently never fires.
    return os.path.realpath(
        os.path.expanduser(override or "~/Documents/Projects/claude-config")
    )


MARKER = ".audit-owed"
CONFIG_PREFIXES = ("skills/", "scripts/", "hooks/")
CONFIG_FILES = ("CLAUDE.md",)


def is_config_asset(path: str) -> bool:
    return path.startswith(CONFIG_PREFIXES) or path in CONFIG_FILES


def failed(response) -> bool:
    """True only when the payload positively says the command failed.

    Narrow on purpose. PostToolUse's `tool_response` for Bash carries
    stdout/stderr/interrupted and no exit status, so an exit code cannot be
    read from it -- an earlier version looked for `exit_code`/`is_error`, which
    are transcript fields rather than hook-payload ones, and the guard was
    inert. `staged_changes` below is the real check; this catches the one case
    the payload does report.
    """
    return bool(isinstance(response, dict) and response.get("interrupted"))


def staged_changes(repo: str) -> bool:
    """True when the index still holds staged changes.

    A payload-independent success signal, which is what the above cannot be. A
    commit that completed leaves the index clean; one that pre-commit rejected
    leaves the staged set restored -- and this repo runs ruff with
    --exit-non-zero-on-fix, so a rejected-then-retried commit is routine.

    Returns False when git cannot answer, so an unexpected environment
    degrades to recording rather than to silence.
    """
    try:
        out = subprocess.run(
            ["git", "-C", repo, "diff", "--cached", "--quiet"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode != 0


def current_branch(repo: str) -> str:
    """The checked-out branch, or "" when git cannot say."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


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
            # Under the 10s timeout register_hooks.py writes for every hook.
            # At 20s Claude Code kills the hook first and the graceful
            # `return []` below is unreachable.
            timeout=5,
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

    if failed(data.get("tool_response")) or staged_changes(repo):
        return

    touched = {p for p in committed_paths(repo) if is_config_asset(p)}
    if not touched:
        return

    # Scoped by branch: the obligation is an audit for what *this* branch
    # changed. Unscoped, switching branches carries the warning across and the
    # obvious fix -- clearing it -- discards the other branch's obligation.
    # The format is duplicated in scripts/audit_assets.py rather than imported,
    # because a hook must run under whatever interpreter settings.json names
    # and cannot depend on this repo's layout.
    branch = current_branch(repo)
    marker = os.path.join(repo, MARKER)
    try:
        with open(marker) as fh:
            lines = {line.rstrip("\n") for line in fh if line.strip()}
    except OSError:
        lines = set()

    mine = {f"{branch}\t{asset}" for asset in touched}
    if mine <= lines:
        # Already owed for these assets on this branch. Asking again on every
        # later commit is the nagging this design exists to avoid.
        return

    lines |= mine
    try:
        with open(marker, "w") as fh:
            fh.write("\n".join(sorted(lines)) + "\n")
    except OSError:
        # Cannot record it, so do not claim it was recorded.
        return

    # A set, not a list: a marker written before branch scoping existed holds
    # unscoped lines, and an asset present both ways was listed twice. Found in
    # production, by this hook reporting the same path to itself twice.
    owed = sorted(
        {
            line.partition("\t")[2] or line
            for line in lines
            if line.partition("\t")[0] == branch or "\t" not in line
        }
    )
    # Count and list come from the same set. Pairing len(all) with a list of
    # only the new ones read as "5 assets (scripts/x.py)" with no ellipsis.
    # json.dumps per path: these come from `git diff-tree` and land in agent
    # context, so they are content this repo did not author in the place an
    # instruction would be obeyed. Same framing rule as friction.py's excerpt.
    listed = ", ".join(json.dumps(asset) for asset in owed[:4])
    more = ", ..." if len(owed) > 4 else ""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"This branch has changed {len(owed)} claude-config "
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
