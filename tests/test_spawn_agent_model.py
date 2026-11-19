"""Contract tests for hooks/spawn-agent-model.py, run as a subprocess."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import run_hook

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "spawn-agent-model.py"
BRIEF = {"task_name": "t", "message": "m"}


def denied(payload) -> bool:
    out = run_hook(HOOK, payload)
    if not out:
        return False
    block = json.loads(out)["hookSpecificOutput"]
    assert block["hookEventName"] == "PreToolUse"
    assert block["permissionDecision"] == "deny"
    return True


def spawn(tool_input) -> dict:
    return {"tool_name": "collaborationspawn_agent", "tool_input": tool_input}


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"model": "gpt-6.2-sol"},
        {"fork_turns": "none"},
        {"model": " ", "fork_turns": "none"},
    ],
)
def test_denies_unless_both_stated(extra):
    assert denied(spawn({**BRIEF, **extra}))


@pytest.mark.parametrize("fork", ["none", "all"])
def test_allows_named_choices(fork):
    assert not denied(spawn({**BRIEF, "model": "gpt-6.2-sol", "fork_turns": fork}))


def test_matches_unprefixed_name():
    assert denied({"tool_name": "spawn_agent", "tool_input": BRIEF})


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        {"tool_name": "Bash", "tool_input": {}},
        spawn(None),
        spawn("{}"),
        {"tool_name": "collaborationwait_agent", "tool_input": {}},
    ],
)
def test_silent_on_other_input(payload):
    assert not denied(payload)
