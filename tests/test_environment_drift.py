"""Tests for hooks/environment-drift.py.

The hook loads dep_updates and vscode_extensions from its own checkout by
path; each test monkeypatches those loaded modules, so nothing here reaches
the network, pixi, `code` or a real refresh process.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest
from conftest import dep_report, torch_finding

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "environment-drift.py"


@pytest.fixture
def hook():
    spec = importlib.util.spec_from_file_location("environment_drift", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Spawner:
    """Records refresh launches; a real one would start a detached process."""

    def __init__(self):
        self.argvs: list[list[str]] = []

    def __call__(self, argv):
        self.argvs.append(list(argv))


def clean_ext(hook):
    return hook.vscode_extensions.ExtReport(
        applicable=True,
        missing=[],
        disabled_required=[],
        forbidden_active=[],
        ide=None,
        notes=["workspace-level disables are not read, only the global list"],
    )


@pytest.fixture
def quiet(hook, monkeypatch):
    """A machine and project with nothing to report."""
    monkeypatch.setattr(
        hook.dep_updates, "cached", lambda root, now: dep_report(hook.dep_updates)
    )
    monkeypatch.setattr(
        hook.vscode_extensions, "check", lambda *a, **k: clean_ext(hook)
    )
    return hook


def context(hook, root, spawn):
    return hook.context(root, spawn=spawn, now=0.0, home=root, env={})


def run_main(hook, monkeypatch, capsys, root: Path) -> str:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(root)})))
    hook.main()
    return capsys.readouterr().out


def test_silent_when_clean(quiet, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(quiet, "spawn_refresh", Spawner())
    assert run_main(quiet, monkeypatch, capsys, tmp_path) == ""


def test_a_finding_is_emitted_as_session_start_context(
    quiet, tmp_path, monkeypatch, capsys
):
    found = dep_report(
        quiet.dep_updates, cross_source=[torch_finding(quiet.dep_updates)]
    )
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: found)
    monkeypatch.setattr(quiet, "spawn_refresh", Spawner())
    payload = json.loads(run_main(quiet, monkeypatch, capsys, tmp_path))
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "pytorch-gpu -> torch" in output["additionalContext"]
    assert "Ask the user whether to update" in output["additionalContext"]


def test_an_extension_problem_is_emitted(quiet, tmp_path, monkeypatch):
    bad = clean_ext(quiet)
    bad.missing.append("astral-sh.ty")
    monkeypatch.setattr(quiet.vscode_extensions, "check", lambda *a, **k: bad)
    text = context(quiet, tmp_path, Spawner())
    assert "missing (required): astral-sh.ty" in text


def test_a_raising_module_prints_nothing_and_exits_cleanly(
    quiet, tmp_path, monkeypatch, capsys
):
    def boom(*args, **kwargs):
        raise RuntimeError("broken module")

    monkeypatch.setattr(quiet.dep_updates, "cached", boom)
    monkeypatch.setattr(quiet, "spawn_refresh", Spawner())
    assert run_main(quiet, monkeypatch, capsys, tmp_path) == ""


def test_a_stale_cache_spawns_exactly_one_refresh_and_does_not_wait(
    quiet, tmp_path, monkeypatch
):
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: None)

    def must_not_compute(*args, **kwargs):
        raise AssertionError("the hook must never compute in-process")

    monkeypatch.setattr(quiet.dep_updates, "check", must_not_compute)
    spawn = Spawner()
    text = context(quiet, tmp_path, spawn)
    assert len(spawn.argvs) == 1
    argv = spawn.argvs[0]
    assert argv[0] == sys.executable
    assert Path(argv[1]).name == "dep_updates.py"
    assert argv[2:] == [str(tmp_path), "--refresh"]
    assert "background" in text


def test_a_stale_cache_shows_its_last_known_findings_dated(
    quiet, tmp_path, monkeypatch
):
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: None)
    stale = dep_report(
        quiet.dep_updates, cross_source=[torch_finding(quiet.dep_updates)]
    )
    checked = time.mktime((2026, 9, 22, 12, 0, 0, 0, 0, -1))
    monkeypatch.setattr(quiet.dep_updates, "last_known", lambda root: (stale, checked))
    spawn = Spawner()
    text = context(quiet, tmp_path, spawn)
    assert len(spawn.argvs) == 1
    assert "(as of 2026-09-22; refresh started)" in text.splitlines()[0]
    assert "pytorch-gpu -> torch" in text


def test_a_running_refresh_is_named_and_not_started_again(quiet, tmp_path, monkeypatch):
    # This test process is the live holder the real lock probe will find.
    lock = tmp_path / ".pixi" / "agent-drift" / "refresh.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: None)
    stale = dep_report(
        quiet.dep_updates, cross_source=[torch_finding(quiet.dep_updates)]
    )
    checked = time.mktime((2026, 9, 22, 12, 0, 0, 0, 0, -1))
    monkeypatch.setattr(quiet.dep_updates, "last_known", lambda root: (stale, checked))
    spawn = Spawner()
    text = context(quiet, tmp_path, spawn)
    assert spawn.argvs == []
    assert "(as of 2026-09-22; refresh in progress)" in text.splitlines()[0]


def test_a_stale_clean_cache_refreshes_silently(quiet, tmp_path, monkeypatch):
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: None)
    monkeypatch.setattr(
        quiet.dep_updates,
        "last_known",
        lambda root: (dep_report(quiet.dep_updates), 0.0),
    )
    spawn = Spawner()
    assert context(quiet, tmp_path, spawn) is None
    assert len(spawn.argvs) == 1


def test_a_fresh_cache_spawns_nothing(quiet, tmp_path):
    spawn = Spawner()
    context(quiet, tmp_path, spawn)
    assert spawn.argvs == []


def test_a_non_pixi_project_spawns_nothing(quiet, tmp_path, monkeypatch):
    blank = quiet.dep_updates._blank(False, "")
    monkeypatch.setattr(quiet.dep_updates, "cached", lambda root, now: blank)
    spawn = Spawner()
    assert context(quiet, tmp_path, spawn) is None
    assert spawn.argvs == []
