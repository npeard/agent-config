"""Behavioral tests for the Codex hooks.json registrar."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def registrar():
    return importlib.import_module("register_codex_hooks")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "hooks").mkdir()
    for name in (
        "task-list.py",
        "prose-writing.py",
        "promotion-check.py",
        "audit-owed.py",
        "notify.py",
    ):
        (tmp_path / "hooks" / name).touch()
    return tmp_path


def test_declared_hooks_are_the_supported_static_mapping(registrar, repo: Path):
    """Would catch a Claude-marker parse or an unsupported Codex translation."""
    assert [
        (item.filename, item.event, item.matcher)
        for item in registrar.declared_hooks(repo)
    ] == [
        ("task-list.py", "SessionStart", None),
        ("prose-writing.py", "PreToolUse", "apply_patch|Bash"),
        ("promotion-check.py", "PostToolUse", "apply_patch|Bash"),
        ("audit-owed.py", "PostToolUse", "Bash"),
        ("notify.py", "Stop", None),
    ]


def test_apply_preserves_foreign_handlers_and_is_idempotent(registrar, repo: Path):
    """Would catch replacing an event group or adding duplicate owned handlers."""
    config = {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "foreign-hook"}],
            }
        ],
        "foreignSetting": {"keep": True},
    }

    changes = registrar.apply(config, registrar.declared_hooks(repo))

    assert changes
    assert config["foreignSetting"] == {"keep": True}
    assert config["PreToolUse"][0] == {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "foreign-hook"}],
    }
    assert registrar.apply(config, registrar.declared_hooks(repo)) == []


def test_apply_updates_and_prunes_only_owned_handlers(registrar, repo: Path):
    """Would catch stale commands surviving or a foreign same-event handler being deleted."""
    old_task = repo / "hooks" / "task-list.py"
    config = {
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'"old-python" "{old_task}"',
                        "commandWindows": f'"old-python.exe" "{old_task}"',
                    },
                    {"type": "command", "command": "foreign-session-start"},
                ]
            }
        ],
        "PreToolUse": [
            {
                "matcher": "retired-tool",
                "hooks": [
                    {
                        "type": "command",
                        "command": f'"old-python" "{repo / "hooks" / "retired.py"}"',
                    }
                ],
            }
        ],
    }

    registrar.apply(config, registrar.declared_hooks(repo))

    session_hooks = config["SessionStart"][0]["hooks"]
    assert {hook["command"] for hook in session_hooks} >= {"foreign-session-start"}
    assert any(
        str(registrar.platform_paths.posix_interpreter(repo)) in hook["command"]
        for hook in session_hooks
    )
    assert "retired-tool" not in [
        group.get("matcher") for group in config.get("PreToolUse", [])
    ]


def test_rendered_handlers_use_absolute_unix_and_windows_commands(
    registrar, repo: Path
):
    """Would catch platform-specific commands that depend on the caller's cwd.

    Each field is asserted against its own platform's layout, not against
    `interpreter()`. The previous form compared both to the live host's
    answer, so it passed while the two fields held the same path -- on Windows
    it certified `command` as the POSIX one, and on Linux it certified
    `commandWindows` as the POSIX one. Either way the config named an
    interpreter that does not exist on the platform that would read it, and
    the test agreed.
    """
    config: dict[str, object] = {}

    registrar.apply(config, [registrar.declared_hooks(repo)[0]])

    handler = config["SessionStart"][0]["hooks"][0]
    script = (repo / "hooks" / "task-list.py").resolve()
    posix = registrar.platform_paths.posix_interpreter(repo)
    windows = registrar.platform_paths.windows_interpreter(repo)
    assert handler["command"] == f'"{posix}" "{script}"'
    assert handler["commandWindows"] == f'"{windows}" "{script}"'
    assert handler["timeout"] == 10


def test_the_two_platform_commands_are_not_the_same_path(registrar, repo: Path):
    """The regression that the assertion above used to permit.

    Holds on either host: a single hooks.json entry describes both platforms,
    so the fields must differ by layout (`bin/python` vs `python.exe`) rather
    than both echoing whichever host generated the file.
    """
    config: dict[str, object] = {}

    registrar.apply(config, [registrar.declared_hooks(repo)[0]])

    handler = config["SessionStart"][0]["hooks"][0]
    assert handler["command"] != handler["commandWindows"]
    assert "python.exe" in handler["commandWindows"]
    assert "python.exe" not in handler["command"]
    assert "bin" in handler["command"]


def test_main_creates_dated_backup_before_atomic_update(
    registrar, repo: Path, tmp_path: Path
):
    """Would catch overwriting a user's configuration without a recoverable copy."""
    settings = tmp_path / "hooks.json"
    original = b'{"foreign": true}\n'
    settings.write_bytes(original)

    assert registrar.main(["--settings", str(settings), "--repo", str(repo)]) == 0

    backups = list(tmp_path.glob("hooks.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert json.loads(settings.read_text(encoding="utf-8"))["foreign"] is True


def test_check_preserves_valid_stale_settings_without_backup(
    registrar, repo: Path, tmp_path: Path
):
    """Would catch check mode writing a valid configuration while reporting drift."""
    settings = tmp_path / "hooks.json"
    original = b'{\n  "foreign": true\n}\n'
    settings.write_bytes(original)

    assert (
        registrar.main(["--check", "--settings", str(settings), "--repo", str(repo)])
        == 1
    )
    assert settings.read_bytes() == original
    assert list(tmp_path.glob("hooks.json.*.bak")) == []


def test_check_and_invalid_json_never_change_bytes(
    registrar, repo: Path, tmp_path: Path
):
    """Would catch check mode or malformed input silently rewriting configuration."""
    settings = tmp_path / "hooks.json"
    settings.write_bytes(b"not json\n")

    assert (
        registrar.main(["--check", "--settings", str(settings), "--repo", str(repo)])
        == 1
    )
    assert settings.read_bytes() == b"not json\n"
    assert registrar.main(["--settings", str(settings), "--repo", str(repo)]) == 1
    assert settings.read_bytes() == b"not json\n"
