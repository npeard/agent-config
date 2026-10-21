"""Semantics of hooks/hook_lib.py, the module the hooks load by path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "hooks" / "hook_lib.py"
spec = importlib.util.spec_from_file_location("hook_lib", SOURCE)
hook_lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook_lib)


@pytest.fixture(autouse=True)
def private_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hook_lib.tempfile, "gettempdir", lambda: str(tmp_path))


def test_a_key_is_claimed_once():
    assert hook_lib.claim("t", "k") is True
    assert hook_lib.claim("t", "k") is False


def test_keys_and_names_are_independent():
    assert hook_lib.claim("t", "a") is True
    assert hook_lib.claim("t", "b") is True
    assert hook_lib.claim("other", "a") is True


def test_a_filesystem_error_fires(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args, **kwargs):
        raise PermissionError

    monkeypatch.setattr(hook_lib.os, "open", refuse)
    assert hook_lib.claim("t", "k") is True
    assert hook_lib.claim("t", "k") is True


def test_claim_for_is_once_per_session_agent_and_scope():
    assert hook_lib.claim_for("t", "s", None, "x") is True
    assert hook_lib.claim_for("t", "s", None, "x") is False
    assert hook_lib.claim_for("t", "s", "sub", "x") is True
    assert hook_lib.claim_for("t", "s", None, "y") is True
    assert hook_lib.claim_for("t", "s2", None, "x") is True


@pytest.mark.parametrize("session", [None, ""])
def test_claim_for_without_a_session_always_fires(session):
    assert hook_lib.claim_for("t", session, None, "x") is True
    assert hook_lib.claim_for("t", session, None, "x") is True


def test_deny_prints_the_pretooluse_refusal(capsys):
    hook_lib.deny("no")
    assert json.loads(capsys.readouterr().out) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "no",
        }
    }
