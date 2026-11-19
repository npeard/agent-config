#!/usr/bin/env python3
# claude-hook: PreToolUse spawn_agent
"""Require Codex `spawn_agent` calls to name their model and their history.

The Codex counterpart of agent-model.py, for a worse default. Omitting
`model` inherits the parent's model, and omitting `fork_turns` defaults to
`all`, so the child re-sends the parent's entire conversation on every turn.
In the picdev session of 2026-11-18, six spawns passed only `task_name` and
`message`. Every child ran gpt-6.2-sol/medium and began at 86k-155k tokens
of inherited context for briefs of about 2k characters. The tree read about
57M input tokens in 35 minutes, and the workspace ran out of credits.

Like agent-model.py this denies, and each value only has to be stated:
`fork_turns: "all"` and the parent's own model are both still allowed.
The marker exists only to satisfy register_hooks' every-hook-declares
invariant: Claude Code has no tool named spawn_agent, so that entry never
fires. register_codex_hooks.py is what makes it live.
"""

import json
import sys

import hook_lib

REASON = (
    "Pass `model` and `fork_turns` to spawn_agent explicitly. Omitting "
    "`fork_turns` forks the whole parent conversation into the child, and "
    'the child re-sends it on every turn. Use `fork_turns: "none"` with a '
    "self-contained brief that gives files as absolute paths, unless the "
    "child truly needs the history. Omitting `model` inherits this session's "
    "model. Name one and set `reasoning_effort`: low effort for mechanical "
    "work (scoped fixes, re-reviewing one diff, sweeps), medium for "
    "implementation and review, a stronger model only for design-sensitive "
    "work."
)


def stated(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    # Codex 0.170 reports the tool under its namespace, as
    # "collaborationspawn_agent" (probed 2026-11-18), so match the suffix.
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.endswith("spawn_agent"):
        return
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    if stated(tool_input.get("model")) and stated(tool_input.get("fork_turns")):
        return
    hook_lib.deny(REASON)


if __name__ == "__main__":
    main()
