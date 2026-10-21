"""Tests for hooks/agent-resume-size.py.

The silent cases carry the weight: a hook that blocked a message to `main` or
a teammate would break ordinary messaging, which is worse than the bug it
guards. Fixtures are synthesized from the documented hook contract (see
tests/fixtures/hooks/README.md).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "agent-resume-size.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hooks"

_spec = importlib.util.spec_from_file_location("agent_resume_size", HOOK)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def usage_line(total: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": total - 10 - 100,
                    "cache_creation_input_tokens": 100,
                    "output_tokens": 7,
                }
            },
        }
    )


def make_session(tmp_path: Path, agent: str, lines: list[str]) -> Path:
    """Lay out <session>.jsonl beside <session>/subagents/agent-<agent>.jsonl
    and return the parent transcript path the hook receives."""
    parent = tmp_path / "sess.jsonl"
    parent.write_text("")
    sub = tmp_path / "sess" / "subagents"
    sub.mkdir(parents=True)
    (sub / f"agent-{agent}.jsonl").write_text("\n".join(lines) + "\n")
    return parent


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


def send(transcript: Path, to: str) -> dict:
    return {
        "tool_name": "SendMessage",
        "transcript_path": str(transcript),
        "tool_input": {"to": to, "message": "one more fix"},
    }


def deny_reason(payload) -> str | None:
    out = run_hook(payload)
    if not out:
        return None
    block = json.loads(out)["hookSpecificOutput"]
    assert block["hookEventName"] == "PreToolUse"
    assert block["permissionDecision"] == "deny"
    return block["permissionDecisionReason"]


def test_denies_a_large_target_from_the_fixture_transcript(tmp_path):
    parent = make_session(tmp_path, "abc", [])
    shutil.copy(
        FIXTURE / "subagent-transcript.jsonl",
        tmp_path / "sess" / "subagents" / "agent-abc.jsonl",
    )
    reason = deny_reason(send(parent, "abc"))
    assert reason
    assert "fresh" in reason
    assert "report file" in reason


def test_allows_below_the_cap(tmp_path):
    parent = make_session(tmp_path, "abc", [usage_line(100_000)])
    assert deny_reason(send(parent, "abc")) is None


def test_uses_the_last_usage_line(tmp_path):
    parent = make_session(tmp_path, "abc", [usage_line(400_000), usage_line(90_000)])
    assert deny_reason(send(parent, "abc")) is None


@pytest.mark.parametrize("to", ["main", "researcher", "../escape"])
def test_allows_a_target_without_a_transcript(tmp_path, to):
    parent = make_session(tmp_path, "abc", [usage_line(400_000)])
    assert deny_reason(send(parent, to)) is None


def test_skips_a_malformed_line_and_uses_the_last_good_one(tmp_path):
    parent = make_session(tmp_path, "abc", [usage_line(400_000), "{not json"])
    assert deny_reason(send(parent, "abc"))


def test_allows_when_nothing_parses(tmp_path):
    parent = make_session(tmp_path, "abc", ["{not json", "also not"])
    assert deny_reason(send(parent, "abc")) is None


@pytest.mark.parametrize("body", ["", "not json", "[1]", "null"])
def test_unusable_stdin_is_silent(body):
    assert run_hook(body) == ""


def test_missing_transcript_path_is_silent():
    assert run_hook({"tool_name": "SendMessage", "tool_input": {"to": "abc"}}) == ""


def test_large_transcript_is_read_through_its_tail(tmp_path, monkeypatch):
    pad = json.dumps({"type": "user", "message": {"content": "x" * 1000}})
    lines = [pad] * 3000 + [usage_line(400_000)]
    path = tmp_path / "big.jsonl"
    path.write_text("\n".join(lines) + "\n")
    assert path.stat().st_size > 3_000_000

    read = 0
    real_open = Path.open

    def counting_open(self, *args, **kwargs):
        handle = real_open(self, *args, **kwargs)
        real_read = handle.read

        def read_counted(*a, **k):
            nonlocal read
            data = real_read(*a, **k)
            read += len(data)
            return data

        handle.read = read_counted
        return handle

    monkeypatch.setattr(Path, "open", counting_open)
    assert hook.context_tokens(path) == 400_000
    assert read < 1_000_000


def test_widens_once_when_the_tail_holds_no_usage(tmp_path):
    pad = json.dumps({"type": "user", "message": {"content": "x" * 1000}})
    # ~300 KiB of padding after the usage line pushes it out of the first window.
    lines = [usage_line(123_456)] + [pad] * 300
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines) + "\n")
    assert hook.context_tokens(path) == 123_456


def synthetic_limit_line() -> str:
    # Shape of the turn Claude Code appends when a session limit hits: a
    # synthetic model with all-zero usage, written after the real last turn.
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "model": "<synthetic>",
                "role": "assistant",
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "content": [{"type": "text", "text": "You've hit your session limit"}],
            },
            "isApiErrorMessage": True,
        }
    )


def test_skips_a_synthetic_session_limit_turn(tmp_path):
    parent = make_session(
        tmp_path, "abc", [usage_line(400_000), synthetic_limit_line()]
    )
    assert deny_reason(send(parent, "abc"))


def test_skips_a_zero_usage_turn_from_a_real_model(tmp_path):
    zero = json.loads(usage_line(400_000))
    zero["message"]["usage"] = {"input_tokens": 0}
    parent = make_session(tmp_path, "abc", [usage_line(400_000), json.dumps(zero)])
    assert deny_reason(send(parent, "abc"))


def test_resolves_a_named_target_through_its_meta_file(tmp_path):
    parent = make_session(tmp_path, "a7ae2b", [usage_line(400_000)])
    sub = tmp_path / "sess" / "subagents"
    (sub / "agent-a7ae2b.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "name": "code-review"})
    )
    (sub / "agent-other.meta.json").write_text("{not json")
    assert deny_reason(send(parent, "code-review"))
    assert deny_reason(send(parent, "someone-else")) is None
