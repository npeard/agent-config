"""Tests for scripts/register_hooks.py.

Two invariants live in different places, deliberately. That every hook
*declares* its event is repo state, so it is gated here. That every declared
hook is *registered* is machine state -- a fresh clone correctly has none --
so preflight reports it instead.
"""

from __future__ import annotations

import json
import os
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

    def test_a_hook_may_declare_several_events(self, tmp_path: Path):
        """notify.py answers Stop, Notification and PreToolUse from one file,
        because the alternative is three copies of one sound table."""
        (tmp_path / "h.py").write_text(
            f"#!/usr/bin/env python3\n{MARKER} Stop\n{MARKER} PreToolUse Write\n"
        )
        assert register_hooks.declared_hooks(tmp_path) == [
            ("h.py", "Stop", None),
            ("h.py", "PreToolUse", "Write"),
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
        python3, below the declared floor. Legacy joined-string form, since
        that is what a pre-migration settings.json holds on disk."""
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
        hook = settings["hooks"]["PostToolUse"][0]["hooks"][0]
        assert hook["args"][0].endswith(str(Path("hooks") / "promotion-check.py"))
        expected = "python.exe" if os.name == "nt" else "/.pixi/envs/dev/bin/python"
        assert expected in hook["command"]

    def test_migrates_the_new_form_idempotently(self):
        """Running registration against settings already holding the new
        command+args form must be a no-op -- the duplication bug this task
        exists to fix showed up only because repo_hook_in/invokes inspected
        `command` alone and never recognised this form."""
        settings: dict = {}
        register_hooks.apply(settings, self.hooks())
        hook = settings["hooks"]["PostToolUse"][0]["hooks"][0]
        assert "args" in hook  # confirms the fixture is genuinely the new form
        assert register_hooks.apply(settings, self.hooks()) == []

    def test_migrates_the_legacy_joined_string_without_duplicating(self):
        """A user upgrading from an older install has joined-string entries
        on disk. They must be recognised and updated in place, never
        duplicated -- the concrete harm this task exists to fix."""
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write|Edit",
                        "hooks": [
                            {
                                "type": "command",
                                "command": (
                                    f"{register_hooks.INTERPRETER} "
                                    f"{register_hooks.HOOKS_DIR / 'promotion-check.py'}"
                                ),
                                "timeout": 10,
                            }
                        ],
                    }
                ]
            }
        }
        changes = register_hooks.apply(settings, self.hooks())
        assert len(settings["hooks"]["PostToolUse"]) == 1
        hooks = settings["hooks"]["PostToolUse"][0]["hooks"]
        assert len(hooks) == 1
        assert any("updated" in c for c in changes)
        command, args = register_hooks.command_for("promotion-check.py")
        assert hooks[0]["command"] == command
        assert hooks[0]["args"] == args
        # A second run against the now-migrated settings is a no-op.
        assert register_hooks.apply(settings, self.hooks()) == []

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

    def test_a_hook_whose_name_is_a_suffix_of_another_is_not_confused(self):
        """The match was `filename in command`, so introducing a `list.py`
        claimed `task-list.py`'s registration and overwrote its command --
        silently unregistering a live hook, with no change reported."""
        command, args = register_hooks.command_for("task-list.py")
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": command,
                                "args": args,
                            }
                        ]
                    }
                ]
            }
        }
        register_hooks.apply(
            settings,
            [("task-list.py", "SessionStart", None), ("list.py", "SessionStart", None)],
        )
        names = [
            Path(a).name
            for e in settings["hooks"]["SessionStart"]
            for h in e["hooks"]
            for a in h["args"]
        ]
        assert sorted(names) == ["list.py", "task-list.py"]

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


class TestPrune:
    """apply() could only add. Nothing scanned the registry for commands
    naming hooks that no longer exist, so a deleted hook stayed registered
    forever and a renamed one registered twice with one entry pointing at a
    file that was gone -- and --check, reporting only what apply() would
    change, left preflight blind to all of it.
    """

    def registry(self, event, *filenames):
        def hook_for(name):
            command, args = register_hooks.command_for(name)
            return {"type": "command", "command": command, "args": args, "timeout": 10}

        return {"hooks": {event: [{"hooks": [hook_for(name)]} for name in filenames]}}

    def commands(self, settings, event):
        # Last token covers both forms: the script is args[-1] in the new
        # form, and the tail of the joined string in the legacy form some
        # cases here deliberately still use.
        return sorted(
            register_hooks._tokens(h)[-1].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            for e in settings["hooks"].get(event, [])
            for h in e["hooks"]
        )

    def test_a_deleted_hooks_registration_is_removed(self):
        settings = self.registry("SessionStart", "gone.py", "task-list.py")
        changes = register_hooks.apply(
            settings, [("task-list.py", "SessionStart", None)]
        )
        assert changes == ["unregistered SessionStart -> gone.py"]
        assert self.commands(settings, "SessionStart") == ["task-list.py"]

    def test_an_event_the_hook_no_longer_declares_is_removed(self):
        """The rename case's twin: the file still exists, but its marker moved
        to another event, leaving a live-looking registration under the old
        one."""
        settings = self.registry("Stop", "task-list.py")
        register_hooks.apply(settings, [("task-list.py", "SessionStart", None)])
        assert "Stop" not in settings["hooks"]
        assert self.commands(settings, "SessionStart") == ["task-list.py"]

    def test_an_entry_whose_last_command_died_is_dropped_whole(self):
        """Leaving the husk behind would keep its matcher registered against
        an entry that can no longer run anything."""
        settings = self.registry("PostToolUse", "gone.py")
        settings["hooks"]["PostToolUse"][0]["matcher"] = "Write"
        register_hooks.apply(settings, [])
        assert settings["hooks"] == {}

    def test_a_hook_registered_twice_under_one_event_is_deduplicated(self):
        """apply() stopped at the first entry matching by basename, so a
        machine whose checkout had moved kept the old registration beside the
        rewritten one: identical commands, the hook firing twice per tool
        call, and every later run reporting "already registered". prune()
        cannot reach it either -- the name is still declared."""
        _promotion_check_command, _promotion_check_args = register_hooks.command_for(
            "promotion-check.py"
        )
        settings = {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "/old/clone/hooks/promotion-check.py",
                            }
                        ],
                    },
                    {
                        "matcher": "Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": _promotion_check_command,
                                "args": _promotion_check_args,
                                "timeout": 10,
                            }
                        ],
                    },
                ]
            }
        }
        changes = register_hooks.apply(
            settings, [("promotion-check.py", "PostToolUse", "Write")]
        )
        assert self.commands(settings, "PostToolUse") == ["promotion-check.py"]
        assert any("duplicate" in c for c in changes), changes

    def test_a_command_outside_this_repo_is_never_removed(self):
        """Only this repo's hooks directory is ours to prune. Another tool's
        registration, or a path from a previous clone location, is not."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {"hooks": [{"type": "command", "command": "/elsewhere/gone.py"}]}
                ]
            }
        }
        assert register_hooks.apply(settings, []) == []
        assert self.commands(settings, "SessionStart") == ["gone.py"]

    def test_check_reports_a_stale_registration_and_writes_nothing(
        self, tmp_path: Path
    ):
        """Registered fully first, so the only remaining drift is the stale
        entry -- otherwise this would pass on the additions alone and say
        nothing about whether preflight can see a dead registration."""
        settings = tmp_path / "settings.json"
        register_hooks.main(["--settings", str(settings)])
        assert register_hooks.main(["--check", "--settings", str(settings)]) == 0
        current = json.loads(settings.read_text())
        command, args = register_hooks.command_for("gone.py")
        current["hooks"]["SessionStart"].append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "args": args,
                    }
                ]
            }
        )
        settings.write_text(json.dumps(current))
        before = settings.read_text()
        assert register_hooks.main(["--check", "--settings", str(settings)]) == 1
        assert settings.read_text() == before


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

    def backups(self, tmp_path: Path) -> list[str]:
        return sorted(
            json.loads(p.read_text())["model"] for p in tmp_path.glob("*.bak")
        )

    def test_backup_is_written_before_the_first_change(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text('{"model": "opus"}\n')
        register_hooks.main(["--settings", str(settings)])
        assert self.backups(tmp_path) == ["opus"]

    def test_a_second_run_keeps_the_first_backup(self, tmp_path: Path):
        """The name was a fixed `.bak`, so the second run overwrote the only
        copy of the state before the first -- and three generations of real
        settings backups had already been lost that way."""
        settings = tmp_path / "settings.json"
        for model in ("first", "second"):
            settings.write_text(json.dumps({"model": model}))
            assert register_hooks.main(["--settings", str(settings)]) == 0
        assert self.backups(tmp_path) == ["first", "second"]

    def test_invalid_json_is_refused_not_overwritten(self, tmp_path: Path):
        settings = tmp_path / "settings.json"
        settings.write_text("{not json")
        assert register_hooks.main(["--settings", str(settings)]) == 1
        assert settings.read_text() == "{not json"

    def test_absent_settings_is_created_and_registered(self, tmp_path: Path):
        """A machine with no settings.json is exactly a new machine, and the
        old "nothing to do" plus exit 0 brought one up with zero hooks --
        reproducing verbatim the never-wired-up failure this script exists to
        prevent."""
        settings = tmp_path / "fresh" / "settings.json"
        assert register_hooks.main(["--settings", str(settings)]) == 0
        registered = json.loads(settings.read_text())["hooks"]
        assert registered
        for _, event, _ in register_hooks.declared_hooks():
            assert event in registered

    def test_check_calls_an_absent_settings_file_drift(self, tmp_path: Path):
        """--check returning 0 here made preflight print `[ok] hooks
        registered` on precisely the machine it exists to protect."""
        settings = tmp_path / "nope.json"
        assert register_hooks.main(["--check", "--settings", str(settings)]) == 1
        assert not settings.exists()


class TestSpacedRepoPath:
    """A repo path containing a space -- "/Users/me/My Projects/..." -- is
    ordinary on macOS and Windows alike. Legacy joined commands were parsed
    with str.split(), which shredded such a path into fragments that named no
    file, so repo_hook_in returned None and prune could never unregister a
    stale hook on those machines. The command+args write path was already
    fixed for this; this is the same hazard on the read path.
    """

    SPACED = Path("/Users/me/My Projects/agent-config")

    @pytest.fixture(autouse=True)
    def _spaced_repo(self, monkeypatch: pytest.MonkeyPatch):
        hooks_dir = self.SPACED / "hooks"
        monkeypatch.setattr(register_hooks, "HOOKS_DIR", hooks_dir)
        monkeypatch.setattr(
            register_hooks,
            "INTERPRETER",
            self.SPACED / ".pixi" / "envs" / "dev" / "bin" / "python",
        )
        return hooks_dir

    def legacy(self, filename):
        return {
            "type": "command",
            "command": (
                f"{register_hooks.INTERPRETER} {register_hooks.HOOKS_DIR / filename}"
            ),
            "timeout": 10,
        }

    def test_repo_hook_in_finds_the_hook_despite_the_space(self):
        assert register_hooks.repo_hook_in(self.legacy("notify.py")) == "notify.py"

    def test_a_stale_legacy_registration_is_pruned(self):
        settings = {"hooks": {"SessionStart": [{"hooks": [self.legacy("gone.py")]}]}}
        changes = register_hooks.apply(settings, [])
        assert changes == ["unregistered SessionStart -> gone.py"]
        assert settings["hooks"] == {}

    def test_a_legacy_registration_migrates_in_place_exactly_once(self):
        settings = {
            "hooks": {
                "SessionStart": [{"hooks": [self.legacy("task-list.py")]}],
            }
        }
        hooks = [("task-list.py", "SessionStart", None)]
        register_hooks.apply(settings, hooks)
        entries = settings["hooks"]["SessionStart"]
        assert len(entries) == 1 and len(entries[0]["hooks"]) == 1
        command, args = register_hooks.command_for("task-list.py")
        assert entries[0]["hooks"][0]["command"] == command
        assert entries[0]["hooks"][0]["args"] == args
        assert register_hooks.apply(settings, hooks) == []

    def test_a_foreign_command_with_a_space_is_still_left_alone(self):
        """Widening the parse must not widen ownership: only a path whose
        parent is exactly this repo's hooks dir is ours to remove."""
        settings = {
            "hooks": {
                "SessionStart": [
                    {
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python /Other Tool/hooks/gone.py",
                            }
                        ]
                    }
                ]
            }
        }
        assert register_hooks.apply(settings, []) == []


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
        command, args = register_hooks.command_for("task-list.py")
        expected = "python.exe" if os.name == "nt" else "/.pixi/envs/dev/bin/python"
        assert expected in command
        assert args[0].endswith(str(Path("hooks") / "task-list.py"))
