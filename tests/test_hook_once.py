"""Claim semantics of hooks/hook_once.py, the marker the once-only hooks share."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "hooks" / "hook_once.py"
spec = importlib.util.spec_from_file_location("hook_once", SOURCE)
hook_once = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook_once)


@pytest.fixture(autouse=True)
def private_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(hook_once.tempfile, "gettempdir", lambda: str(tmp_path))


def test_a_key_is_claimed_once():
    assert hook_once.claim("t", "k") is True
    assert hook_once.claim("t", "k") is False


def test_keys_and_names_are_independent():
    assert hook_once.claim("t", "a") is True
    assert hook_once.claim("t", "b") is True
    assert hook_once.claim("other", "a") is True


def test_a_filesystem_error_fires(monkeypatch: pytest.MonkeyPatch):
    def refuse(*args, **kwargs):
        raise PermissionError

    monkeypatch.setattr(hook_once.os, "open", refuse)
    assert hook_once.claim("t", "k") is True
    assert hook_once.claim("t", "k") is True
