"""Tests for hooks/poll-guard.py.

The silent cases carry the weight: a hook that denied `grep sleep log.txt` or
a short `sleep 5` would block ordinary work, which is worse than the bug it
guards. Inputs are synthesized from the documented hook contract (see
tests/fixtures/hooks/README.md): `agent_id` is present only for a subagent.

The loop and sleep rules are asserted on `polls` directly; a few subprocess
cases pin the stdin, exit-code and deny-JSON contract the host depends on.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from conftest import run_hook

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "poll-guard.py"

_spec = importlib.util.spec_from_file_location("poll_guard", HOOK)
poll_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(poll_guard)


def call(command: str, tool="Bash", agent=True) -> dict:
    payload = {"tool_name": tool, "tool_input": {"command": command}}
    if agent:
        payload["agent_id"] = "abc123"
    return payload


def deny_reason(payload) -> str | None:
    out = run_hook(HOOK, payload)
    if not out:
        return None
    block = json.loads(out)["hookSpecificOutput"]
    assert block["hookEventName"] == "PreToolUse"
    assert block["permissionDecision"] == "deny"
    return block["permissionDecisionReason"]


def main_output(payload, monkeypatch, capsys) -> str:
    """What main() prints for `payload`, without a subprocess."""
    body = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(body))
    poll_guard.main()
    return capsys.readouterr().out.strip()


def test_a_subagent_poll_is_denied_with_the_reason():
    reason = deny_reason(call("until test -f out.h5; do sleep 30; done"))
    assert reason
    assert "waiting on" in reason
    assert "compute-job-safety" in reason


def test_the_same_poll_from_the_main_session_is_allowed():
    assert deny_reason(call("sleep 120", agent=False)) is None


@pytest.mark.parametrize("body", ["", "not json"])
def test_unusable_stdin_is_silent_with_a_clean_exit(body):
    assert run_hook(HOOK, body) == ""


@pytest.mark.parametrize(
    "command",
    [
        "until test -f out.h5; do sleep 30; done",
        "while true; do sleep 5; done",
        "for i in 1 2 3; do sleep 30; done",
        "for i in $(seq 100); do test -f out && break; sleep 5; done",
        "for i in {1..20}; do sleep 3; done",
        "for i in $(seq 0 2 10); do sleep 10; done",
        "do { Start-Sleep 5 } until (Test-Path out.h5)",
        "until test -f out.h5\ndo\n  sleep 30\ndone",
        "sleep 120",
        "sleep 2m",
        "cd run && sleep 60",
        "while (-not (Test-Path out.h5)) { Start-Sleep -Seconds 30 }",
        "Start-Sleep -Seconds 120",
        "Start-Sleep 120",
    ],
)
def test_sleep_polling_is_a_poll(command):
    assert poll_guard.polls(command)


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
        "Start-Sleep -Seconds 2",
        "Start-Sleep -Milliseconds 500",
        # Unknowable duration, so treated as 0 s: a false deny would block work.
        "sleep $N",
        "sleep infinity",
        "sleep 'x",
        "for i in $(seq 10); do curl -s :8888 && break; sleep 1; done",
        "for i in 1 2 3; do sleep 1; done",
        "for i in {1..5}; do sleep 2; done",
        "for f in *.log; do gzip $f; sleep 1; done",
        "foreach ($i in 1..10) { Start-Sleep 1 }",
    ],
)
def test_commands_that_only_mention_or_briefly_use_sleep_are_not_polls(command):
    assert not poll_guard.polls(command)


def test_native_windows_path_survives_tokenizing(hook_lib):
    # Without the path fix shlex reads `\U`, `\t` as escapes and drops the
    # backslashes; a loop rule would deny anyway, so assert on the tokens.
    assert hook_lib.shell_commands(r"cat C:\Users\x\tmp\new", hook_lib.tokenize) == [
        ["cat", r"C:\Users\x\tmp\new"]
    ]


@pytest.mark.parametrize("body", ["[1]", "null"])
def test_non_object_stdin_is_silent(body, monkeypatch, capsys):
    assert main_output(body, monkeypatch, capsys) == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"agent_id": "a", "tool_name": "Bash"},
        {"agent_id": "a", "tool_name": "Bash", "tool_input": {"command": 5}},
        {"agent_id": "a", "tool_name": "Read", "tool_input": {"command": "sleep 300"}},
    ],
)
def test_malformed_or_foreign_input_is_silent(payload, monkeypatch, capsys):
    assert main_output(payload, monkeypatch, capsys) == ""


def test_the_powershell_tool_is_checked_too(monkeypatch, capsys):
    out = main_output(call("Start-Sleep 120", tool="PowerShell"), monkeypatch, capsys)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
