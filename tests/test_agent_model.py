"""Contract tests for hooks/agent-model.py.

The hook is a pure JSON filter -- a payload on stdin, an optional payload on
stdout -- so it is exercised through that contract as a subprocess, with no
filesystem or git state involved.

"Tests required" is not optional at tier 1: an untested hook is how
promotion-check silently never fired for months. The cases that matter here
are the *silent* ones -- a hook that denied a `fork` dispatch, or that fired
on a specialist agent carrying its own model, would be worse than no hook,
because it would block work the rule never meant to block.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "agent-model.py"


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


def denied(payload) -> bool:
    out = run_hook(payload)
    if not out:
        return False
    parsed = json.loads(out)
    block = parsed["hookSpecificOutput"]
    # A fired hook must emit the shape Claude Code expects, not just text --
    # a wrong key here is indistinguishable from a hook that never ran.
    assert block["hookEventName"] == "PreToolUse"
    assert block["permissionDecision"] == "deny"
    assert block["permissionDecisionReason"]
    return True


def dispatch(**tool_input) -> dict:
    return {"tool_name": "Agent", "tool_input": tool_input}


class TestFiresOnCatchAllWithoutModel:
    """The case the hook exists for: an absent model on a catch-all type
    resolves to the session model, which is Opus."""

    @pytest.mark.parametrize(
        "subagent_type",
        ["general-purpose", "claude", "default", "", "GENERAL-PURPOSE", " claude "],
    )
    def test_named_catch_all_without_model_is_denied(self, subagent_type: str):
        assert denied(dispatch(subagent_type=subagent_type, prompt="do a thing"))

    def test_absent_subagent_type_is_denied(self):
        """Omitting subagent_type defaults to general-purpose, so it inherits
        the parent model exactly as the named form does."""
        assert denied(dispatch(prompt="do a thing"))

    @pytest.mark.parametrize("model", ["", "   "])
    def test_blank_model_counts_as_absent(self, model: str):
        """A whitespace-only model would satisfy a bare presence check while
        still resolving to the inherited model."""
        assert denied(dispatch(subagent_type="general-purpose", model=model))


class TestStaysSilent:
    """Every way the hook must not block work."""

    @pytest.mark.parametrize("model", ["haiku", "sonnet", "opus", "fable"])
    def test_explicit_model_passes(self, model: str):
        assert not denied(dispatch(subagent_type="general-purpose", model=model))

    def test_fork_passes_without_a_model(self):
        """A fork always inherits the parent model and ignores an override,
        so demanding one would be incoherent."""
        assert not denied(dispatch(subagent_type="fork", prompt="continue"))

    @pytest.mark.parametrize(
        "subagent_type", ["Explore", "Plan", "claude-code-guide", "statusline-setup"]
    )
    def test_specialist_agents_pass_without_a_model(self, subagent_type: str):
        """A named specialist may pin its own model in its definition; firing
        here would override a deliberate choice, and a specialist this hook
        has never heard of must not start failing."""
        assert not denied(dispatch(subagent_type=subagent_type, prompt="look"))

    def test_other_tools_pass(self):
        """The settings.json matcher narrows to Agent, but the hook must not
        depend on that file being correct."""
        assert not denied({"tool_name": "Bash", "tool_input": {"command": "ls"}})


class TestMalformedInput:
    """A hook that tracebacks is noisier than one that declines."""

    @pytest.mark.parametrize("body", ["", "not json", "[1, 2]", '"a string"', "null"])
    def test_unusable_body_is_silent(self, body: str):
        assert run_hook(body) == ""

    @pytest.mark.parametrize("tool_input", [None, "a string", 42, []])
    def test_non_dict_tool_input_is_silent(self, tool_input):
        assert run_hook({"tool_name": "Agent", "tool_input": tool_input}) == ""

    def test_non_string_subagent_type_is_silent(self):
        """The harness will reject this call on its own; denying it here would
        report the wrong reason."""
        assert run_hook(dispatch(subagent_type=42)) == ""
