"""Tests for scripts/register_hooks.py.

Two invariants live in different places, deliberately. That every hook
*declares* its event is repo state, so it is gated here. That every declared
hook is *registered* is machine state -- a fresh clone correctly has none --
so preflight reports it instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import register_hooks

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = "# claude-hook:"


class TestRepoInvariant:
    def test_every_hook_declares_its_event(self):
        """A hook with no marker cannot be registered, so it would ship inert
        -- which is exactly how task-list.py was written, tested, documented
        as registered, and never wired up."""
        assert register_hooks.undeclared() == []

    def test_the_repo_declares_at_least_one_hook(self):
        assert register_hooks.declared_hooks()

    def test_declarations_name_a_plausible_event(self):
        known = {
            "SessionStart",
            "SessionEnd",
            "PostToolUse",
            "PreToolUse",
            "UserPromptSubmit",
            "Stop",
            "SubagentStop",
            "PreCompact",
            "Notification",
        }
        for name, event, _ in register_hooks.declared_hooks():
            assert event in known, f"{name} declares unknown event {event}"


class TestParsing:
    def test_reads_event_and_matcher(self, tmp_path: Path):
        (tmp_path / "h.py").write_text(
            f"#!/usr/bin/env python3\n{MARKER} PostToolUse Write|Edit\n"
        )
        assert register_hooks.declared_hooks(tmp_path) == [
            ("h.py", "PostToolUse", "Write|Edit")
        ]

    def test_matcher_is_optional(self, tmp_path: Path):
        (tmp_path / "h.py").write_text(f"{MARKER} SessionStart\n")
        assert register_hooks.declared_hooks(tmp_path) == [
            ("h.py", "SessionStart", None)
        ]

    def test_marker_must_be_near_the_top(self, tmp_path: Path):
        """Scanning the whole file would match the string in a docstring or a
        test fixture."""
        body = "\n" * 40 + f"{MARKER} SessionStart\n"
        (tmp_path / "h.py").write_text(body)
        assert register_hooks.declared_hooks(tmp_path) == []

    def test_undeclared_hooks_are_listed(self, tmp_path: Path):
        (tmp_path / "declared.py").write_text(f"{MARKER} SessionStart\n")
        (tmp_path / "silent.py").write_text("print('hi')\n")
        assert register_hooks.undeclared(tmp_path) == ["silent.py"]


class TestMerge:
    def hooks(self):
        return [
            ("task-list.py", "SessionStart", None),
            ("promotion-check.py", "PostToolUse", "Write|Edit"),
        ]

    def test_registers_into_an_empty_settings(self):
        settings: dict = {}
        changes = register_hooks.apply(settings, self.hooks())
        assert len(changes) == 2
        assert set(settings["hooks"]) == {"SessionStart", "PostToolUse"}

    def test_is_idempotent(self):
        settings: dict = {}
        register_hooks.apply(settings, self.hooks())
        assert register_hooks.apply(settings, self.hooks()) == []

    def test_updates_a_stale_interpreter_without_duplicating(self):
        """The live drift: promotion-check was registered under a bare
        python3, below the declared floor."""
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 /old/path/promotion-check.py",
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            }
        }
        changes = register_hooks.apply(settings, self.hooks())
        assert any("interpreter" in c for c in changes)
        assert len(settings["hooks"]["PostToolUse"]) == 1
        command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        assert command.endswith("hooks/promotion-check.py")
        assert "/.pixi/envs/dev/bin/python " in command

    def test_corrects_a_wrong_matcher(self):
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Read",
                        "hooks": [
                            {"type": "command", "command": "x/promotion-check.py"}
                        ],
                    }
                ]
            }
        }
        register_hooks.apply(settings, self.hooks())
        assert settings["hooks"]["PostToolUse"][0]["matcher"] == "Write|Edit"

    def test_leaves_unrelated_hooks_alone(self):
        settings = {
            "hooks": {
                "PostToolUse": [
                    {"hooks": [{"type": "command", "command": "somebody-elses.py"}]}
                ]
            }
        }
        register_hooks.apply(settings, self.hooks())
        commands = [
            h["command"] for e in settings["hooks"]["PostToolUse"] for h in e["hooks"]
        ]
        assert "somebody-elses.py" in commands


class TestMainContract:
    def test_check_mode_reports_and_does_not_write(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text("{}\n")
        before = settings.read_text()
        assert register_hooks.main(["--check", "--settings", str(settings)]) == 1
        assert settings.read_text() == before

    def test_write_then_check_is_clean(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text('{"model": "opus"}\n')
        assert register_hooks.main(["--settings", str(settings)]) == 0
        assert register_hooks.main(["--check", "--settings", str(settings)]) == 0
        # Unrelated settings must survive.
        assert json.loads(settings.read_text())["model"] == "opus"

    def test_backup_is_written_before_the_first_change(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text('{"model": "opus"}\n')
        register_hooks.main(["--settings", str(settings)])
        backup = settings.with_suffix(".json.bak")
        assert backup.is_file()
        assert json.loads(backup.read_text()) == {"model": "opus"}

    def test_invalid_json_is_refused_not_overwritten(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text("{not json")
        assert register_hooks.main(["--settings", str(settings)]) == 1
        assert settings.read_text() == "{not json"

    def test_absent_settings_is_not_an_error(self, tmp_path: Path):
        assert register_hooks.main(["--settings", str(tmp_path / "nope.json")]) == 0


class TestInterpreterPrerequisite:
    """A registered hook names the project interpreter in its command, so that
    binary is a prerequisite for the hook to run at all. An earlier version
    registered before the env existed and reported success, producing hooks
    that could never start.
    """

    def test_refuses_when_the_interpreter_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        settings = tmp_path / "settings.json"
        settings.write_text("{}\n")
        monkeypatch.setattr(
            register_hooks, "INTERPRETER", tmp_path / "nonexistent" / "python"
        )
        assert register_hooks.main(["--settings", str(settings)]) == 1
        # Refusing must also mean not half-writing.
        assert json.loads(settings.read_text()) == {}

    def test_command_names_the_project_interpreter(self):
        command = register_hooks.command_for("task-list.py")
        assert "/.pixi/envs/dev/bin/python " in command
        assert command.endswith("hooks/task-list.py")
