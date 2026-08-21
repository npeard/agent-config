"""Contract tests for hooks/notify.py.

The hook's whole observable effect is which command it spawns, so `spawn` is
the seam: every test here asserts on the argv list rather than on a sound
anyone can hear. Two of them run the file as a subprocess instead, because
"declines instead of tracebacking" is a property of the process, not of a
function.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "notify.py"


def load():
    """The hook as a module.

    Imported by path because hooks/ is not a package and the filename is not
    guaranteed to be an identifier -- its siblings are prose-writing.py and
    task-list.py.
    """
    spec = importlib.util.spec_from_file_location("notify_hook", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def notify():
    return load()


@pytest.fixture
def spawned(notify, monkeypatch):
    """Every argv the hook would have run, in order."""
    calls: list[list[str]] = []
    monkeypatch.setattr(notify, "spawn", calls.append)
    monkeypatch.delenv("CLAUDE_NOTIFY_OFF", raising=False)
    return calls


def feed(notify, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    notify.main()


class TestReason:
    def test_stop_is_the_turn_finishing(self, notify):
        assert notify.reason({"hook_event_name": "Stop"}) == "done"

    def test_a_continued_stop_is_not_announced_twice(self, notify):
        """stop_hook_active means some Stop hook fed the model more work, so
        the turn this fires for was already announced on the first pass."""
        payload = {"hook_event_name": "Stop", "stop_hook_active": True}
        assert notify.reason(payload) is None

    @pytest.mark.parametrize(
        ("notification_type", "expected"),
        [
            ("permission_prompt", "permission"),
            ("worker_permission_prompt", "permission"),
            ("idle_prompt", "idle"),
            ("agent_needs_input", "idle"),
        ],
    )
    def test_notifications_that_want_an_answer(
        self, notify, notification_type, expected
    ):
        payload = {
            "hook_event_name": "Notification",
            "notification_type": notification_type,
        }
        assert notify.reason(payload) == expected

    @pytest.mark.parametrize(
        "notification_type",
        ["auth_success", "quota_auto_resume_fired", "computer_use_enter", "unheard_of"],
    )
    def test_housekeeping_notifications_are_silent(self, notify, notification_type):
        """The event carries progress and status types too. Pinging on those
        is what teaches someone to ignore the ping."""
        payload = {
            "hook_event_name": "Notification",
            "notification_type": notification_type,
        }
        assert notify.reason(payload) is None

    def test_askuserquestion_is_a_question(self, notify):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion"}
        assert notify.reason(payload) == "question"

    def test_another_pretooluse_is_silent(self, notify):
        """The settings.json matcher already narrows this, but a hook that
        needs a file it cannot read to be correct misfires the day that file
        is edited by hand."""
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Write"}
        assert notify.reason(payload) is None

    def test_an_unknown_event_is_silent(self, notify):
        assert notify.reason({"hook_event_name": "SessionStart"}) is None


class TestSoundResolution:
    def test_a_bare_name_resolves_against_the_system_sounds(self, notify, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        argv = notify.sound_argv("Hero")
        assert argv[0] == "afplay"
        assert argv[-1] == "/System/Library/Sounds/Hero.aiff"

    def test_a_path_is_used_as_given(self, notify, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert notify.sound_argv("/tmp/custom.wav")[-1] == "/tmp/custom.wav"

    def test_an_unresolvable_name_plays_nothing(self, notify, monkeypatch):
        """Rather than handing afplay a path that does not exist, which fails
        into stderr nobody reads and looks exactly like silence."""
        monkeypatch.setattr(sys, "platform", "darwin")
        assert notify.sound_argv("NotAMacSound") is None

    def test_an_empty_sound_plays_nothing(self, notify):
        assert notify.sound_argv("") is None

    def test_a_bare_name_off_macos_plays_nothing(self, notify, monkeypatch):
        """No other platform has a named system sound set to resolve against."""
        monkeypatch.setattr(sys, "platform", "linux")
        assert notify.sound_argv("Hero") is None

    def test_the_volume_is_passed_to_the_player(self, notify, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(notify, "VOLUME", 0.25)
        assert "0.25" in notify.sound_argv("Hero")


class TestBanner:
    def test_applescript_quotes_are_escaped(self, notify):
        r"""An unescaped " ends the AppleScript literal and the notification
        silently never appears."""
        assert notify.applescript('say "hi" \\ bye') == r"say \"hi\" \\ bye"

    def test_the_title_is_the_project_directory(self, notify):
        assert notify.project({"cwd": "/Users/x/Projects/thesis"}) == "thesis"

    def test_a_missing_cwd_still_has_a_title(self, notify):
        assert notify.project({}) == "Claude Code"


class TestEndToEnd:
    def test_stop_plays_the_done_sound_and_names_the_project(
        self, notify, monkeypatch, spawned
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, {"hook_event_name": "Stop", "cwd": "/w/thesis"})
        assert any("Hero.aiff" in arg for argv in spawned for arg in argv)
        assert any("thesis" in arg for argv in spawned for arg in argv)

    def test_the_notification_message_is_preferred_over_ours(
        self, notify, monkeypatch, spawned
    ):
        """The host says which tool wants permission; nothing written in this
        repo can be more specific than that."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(
            notify,
            monkeypatch,
            {
                "hook_event_name": "Notification",
                "notification_type": "permission_prompt",
                "message": "Claude needs your permission to use Bash",
                "cwd": "/w/thesis",
            },
        )
        assert any("use Bash" in arg for argv in spawned for arg in argv)

    def test_a_silenced_reason_still_shows_its_banner(
        self, notify, monkeypatch, spawned
    ):
        """`idle` ships with no sound. That must mute the sound only -- a
        reason with no sound and no banner would be a dead branch."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(
            notify,
            monkeypatch,
            {"hook_event_name": "Notification", "notification_type": "idle_prompt"},
        )
        assert not any("afplay" in argv[0] for argv in spawned)
        assert spawned

    def test_banner_off_leaves_only_the_sound(self, notify, monkeypatch, spawned):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(notify, "BANNER", False)
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert [argv[0] for argv in spawned] == ["afplay"]

    def test_an_environment_override_wins(self, notify, monkeypatch, spawned):
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("CLAUDE_NOTIFY_SOUND_DONE", "Tink")
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert any("Tink.aiff" in arg for argv in spawned for arg in argv)

    def test_off_mutes_everything(self, notify, monkeypatch, spawned):
        monkeypatch.setenv("CLAUDE_NOTIFY_OFF", "1")
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert spawned == []

    def test_off_is_presence_not_truth(self, notify, monkeypatch, spawned):
        """Documented as presence-based so that nothing has to agree on what
        "0" means; the test pins the documented behaviour."""
        monkeypatch.setenv("CLAUDE_NOTIFY_OFF", "0")
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert spawned == []

    def test_an_unset_off_does_not_mute(self, notify, monkeypatch, spawned):
        monkeypatch.setenv("CLAUDE_NOTIFY_OFF", "")
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert spawned


class TestProcessContract:
    """Run as the host runs it: a payload on stdin, nothing on stdout.

    A notifier has no reply to make, and a Stop hook that prints an
    unrecognized body is a hook that can interfere with the turn it is only
    supposed to announce.
    """

    def run(self, body: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HOOK)],
            input=body,
            capture_output=True,
            text=True,
            check=False,
            env={"CLAUDE_NOTIFY_OFF": "1", "PATH": "/usr/bin:/bin"},
        )

    @pytest.mark.parametrize("body", ["", "{not json", "null", "[]", "42"])
    def test_a_surprising_payload_declines_instead_of_failing(self, body):
        result = self.run(body)
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_a_real_payload_says_nothing(self):
        result = self.run(json.dumps({"hook_event_name": "Stop", "cwd": "/w/x"}))
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


class TestRegistration:
    def test_it_declares_the_three_events_it_answers(self):
        """One file, three events. The marker parser collects every marker in
        the window, so this is also the regression test for that."""
        sys.path.insert(0, str(HOOK.parent.parent / "scripts"))
        import register_hooks

        declared = [
            (event, matcher)
            for name, event, matcher in register_hooks.declared_hooks()
            if name == "notify.py"
        ]
        assert declared == [
            ("Stop", None),
            ("Notification", None),
            ("PreToolUse", "AskUserQuestion"),
        ]
