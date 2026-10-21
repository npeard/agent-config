"""Tests for hooks/poll-guard.py.

The silent cases carry the weight: a hook that denied `grep sleep log.txt` or
a short `sleep 5` would block ordinary work, which is worse than the bug it
guards. Inputs are synthesized from the documented hook contract (see
tests/fixtures/hooks/README.md): `agent_id` is present only for a subagent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "poll-guard.py"


def run_hook(payload) -> str:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    assert not result.stderr, f"hook wrote to stderr: {result.stderr}"
    return result.stdout.strip()


def call(command: str, tool="Bash", agent=True) -> dict:
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if agent:
        payload["agent_id"] = "abc123"
    return payload


def deny_reason(payload) -> str | None:
    out = run_hook(payload)
    if not out:
        return None
    block = json.loads(out)["hookSpecificOutput"]
    assert block["hookEventName"] == "PreToolUse"
    assert block["permissionDecision"] == "deny"
    return block["permissionDecisionReason"]


@pytest.mark.parametrize(
    "command",
    [
        "until test -f out.h5; do sleep 30; done",
        "while true; do sleep 5; done",
        "for i in 1 2 3; do sleep 1; done",
        "until test -f out.h5\ndo\n  sleep 30\ndone",
        "sleep 120",
        "sleep 2m",
        "cd run && sleep 60",
    ],
)
def test_denies_sleep_polling_from_a_subagent(command):
    reason = deny_reason(call(command))
    assert reason
    assert "waiting on" in reason
    assert "compute-job-safety" in reason


@pytest.mark.parametrize(
    "command",
    ["until test -f out.h5; do sleep 30; done", "sleep 120"],
)
def test_allows_the_same_command_from_the_main_session(command):
    assert deny_reason(call(command, agent=False)) is None


@pytest.mark.parametrize(
    "command",
    [
        "sleep 5",
        "sleep 59",
        "sleep 0.5",
        "grep sleep log.txt",
        'echo "sleep 300"',
        "ls sleep_dir/",
        "cat ./sleep",
        "git log --grep='until sleep'",
        "python run.py",
        "sleep",
    ],
)
def test_allows_commands_that_only_mention_or_briefly_use_sleep(command):
    assert deny_reason(call(command)) is None


def test_denies_powershell_sleep_in_a_loop():
    command = "while (-not (Test-Path out.h5)) { Start-Sleep -Seconds 30 }"
    assert deny_reason(call(command, tool="PowerShell"))


def test_denies_a_long_standalone_powershell_sleep():
    assert deny_reason(call("Start-Sleep -Seconds 120", tool="PowerShell"))
    assert deny_reason(call("Start-Sleep 120", tool="PowerShell"))


def test_allows_a_short_powershell_sleep():
    assert deny_reason(call("Start-Sleep -Seconds 2", tool="PowerShell")) is None
    assert deny_reason(call("Start-Sleep -Milliseconds 500", tool="PowerShell")) is None


def test_native_windows_path_does_not_break_parsing():
    command = r"until test -f C:\Users\me\out.h5; do sleep 30; done"
    assert deny_reason(call(command))


@pytest.mark.parametrize("body", ["", "not json", "[1]", "null"])
def test_unusable_stdin_is_silent(body):
    assert run_hook(body) == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"agent_id": "a", "tool_name": "Bash"},
        {"agent_id": "a", "tool_name": "Bash", "tool_input": {"command": 5}},
        {"agent_id": "a", "tool_name": "Bash", "tool_input": {"command": "sleep 'x"}},
        {"agent_id": "a", "tool_name": "Read", "tool_input": {"command": "sleep 300"}},
    ],
)
def test_malformed_or_foreign_input_is_silent(payload):
    assert deny_reason(payload) is None
