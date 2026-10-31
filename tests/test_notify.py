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
import os
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
    """Every argv the hook would have run, in order.

    The double returns True because the real `spawn` reports whether it
    started anything, and arm() takes its marker back when it did not. A
    stub that returned None would make every arming look like a failure.
    """
    calls: list[list[str]] = []

    def record(argv):
        calls.append(argv)
        return True

    monkeypatch.setattr(notify, "spawn", record)
    monkeypatch.delenv("CLAUDE_NOTIFY_OFF", raising=False)
    return calls


def feed(notify, monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    notify.main()


def test_codex_stop_payload_keeps_the_done_notification(notify):
    """Codex's mapped Stop payload retains notify's existing disposition."""
    assert (
        notify.reason(
            {
                "cwd": "/w/thesis",
                "session_id": "codex-session",
                "hook_event_name": "Stop",
            }
        )
        == "done"
    )


def test_portability_docs_mark_agent_and_interaction_hooks_unsupported():
    """Codex must not be presented as supporting unmapped Claude-only policy."""
    portability = (HOOK.parent.parent / "docs" / "PORTABILITY.md").read_text()
    assert "agent-model" in portability
    assert "notification/question" in portability
    assert "unsupported" in portability.lower()


# The bare names sound_argv() is asked to resolve across this file: every
# SOUNDS value, plus the one an override test substitutes.
MAC_SOUND_NAMES = ("Hero", "Glass", "Funk", "Tink")


def mac_sounds_present(notify, monkeypatch, tmp_path):
    """Make every bare macOS sound name resolve, without a real Mac.

    The darwin branch of sound_argv() checks Path.is_file() against
    MAC_SOUND_DIR, a fixed macOS path (/System/Library/Sounds) that exists
    only on an actual Mac.

    Real files under a redirected MAC_SOUND_DIR, not a patched Path.is_file:
    patching the method made *every* is_file() in the process return True, so
    the end-to-end cases below -- which check real files on disk -- were
    unconditionally satisfied and a regression in them could not fail.
    Every assertion here reads the resolved path back off notify.MAC_SOUND_DIR
    or matches the bare filename, so redirecting the constant leaves them
    intact.
    """
    sounds = tmp_path / "Sounds"
    sounds.mkdir(exist_ok=True)
    for name in MAC_SOUND_NAMES:
        (sounds / f"{name}.aiff").write_bytes(b"")
    monkeypatch.setattr(notify, "MAC_SOUND_DIR", sounds)


class TestReason:
    @pytest.mark.parametrize(
        "payload",
        [
            {"hook_event_name": "Stop"},
            {"hook_event_name": "Stop", "background_tasks": []},
        ],
        ids=["field-absent", "field-empty"],
    )
    def test_stop_with_nothing_in_flight_is_the_turn_finishing(self, notify, payload):
        """Absent and empty have to behave alike. The field is optional in
        the host's schema, so reading a missing key as "something is running"
        would mute every turn on a host that omits it."""
        assert notify.reason(payload) == "done"

    @pytest.mark.parametrize(
        "task",
        [
            {"id": "a1", "type": "subagent", "status": "running", "description": "x"},
            {"id": "b1", "type": "shell", "status": "running", "command": "sleep 45"},
            {"id": "c1", "type": "workflow", "status": "pending", "description": "x"},
        ],
    )
    def test_work_still_in_flight_stays_silent(self, notify, task):
        """Stop fires every time the main loop yields, including when it
        yields to wait on a subagent it will be woken up for. Announcing
        those is the noise this gate exists to remove."""
        payload = {"hook_event_name": "Stop", "background_tasks": [task]}
        assert notify.reason(payload) is None

    def test_a_continued_stop_is_not_announced_twice(self, notify):
        """stop_hook_active means some Stop hook fed the model more work, so
        the turn this fires for was already announced on the first pass."""
        payload = {"hook_event_name": "Stop", "stop_hook_active": True}
        assert notify.reason(payload) is None

    @pytest.mark.parametrize(
        ("notification_type", "expected"),
        [
            ("permission_prompt", "permission"),
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
        "notification_type", ["worker_permission_prompt", "agent_needs_input"]
    )
    def test_subagent_notifications_are_silent(self, notify, notification_type):
        """Only the orchestrating agent pings; these come from subagents."""
        payload = {
            "hook_event_name": "Notification",
            "notification_type": notification_type,
        }
        assert notify.reason(payload) is None

    @pytest.mark.parametrize(
        "payload",
        [
            {"hook_event_name": "Stop"},
            {
                "hook_event_name": "Notification",
                "notification_type": "permission_prompt",
            },
            {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion"},
        ],
        ids=["stop", "notification", "question"],
    )
    def test_an_event_inside_a_subagent_is_silent(self, notify, payload):
        """Claude Code adds agent_id to hook input fired inside a subagent."""
        assert notify.reason({**payload, "agent_id": "a1"}) is None

    @pytest.mark.parametrize(
        "notification_type",
        [
            "idle_prompt",
            "auth_success",
            "quota_auto_resume_fired",
            "computer_use_enter",
            "unheard_of",
        ],
    )
    def test_housekeeping_notifications_are_silent(self, notify, notification_type):
        """The event carries progress and status types too. Pinging on those
        is what teaches someone to ignore the ping. `idle_prompt` is here
        rather than in SOUNDS because a prompt sitting open is not news: the
        turn it belongs to was already announced when it ended."""
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


class TestPathClassification:
    """looks_like_a_path() must read the STRING, not the host.

    The prior implementation tested `os.sep in name`, which reads os.sep --
    host state -- rather than the string's own shape. That classified a
    Windows-style override string as a bare name on any POSIX host (os.sep
    is "/", absent from "C:\\Windows\\Media\\tada.wav") and, symmetrically,
    a POSIX-style override as bare on Windows. Every case below asserts the
    same answer regardless of monkeypatched os.sep/os.name, which the old
    version could not satisfy.
    """

    @pytest.mark.parametrize(
        "name",
        [
            r"C:\Windows\Media\tada.wav",
            "/System/Library/Sounds/Hero.aiff",
            "relative/unix.wav",
            r"relative\windows.wav",
            "C:bare-drive-relative.wav",
        ],
    )
    def test_any_path_shaped_string_is_a_path_on_every_host(
        self, notify, monkeypatch, name
    ):
        for fake_sep in ("/", "\\"):
            monkeypatch.setattr(os, "sep", fake_sep)
            assert notify.looks_like_a_path(name) is True

    @pytest.mark.parametrize("name", ["Hero", "Tink", "Glass", ""])
    def test_a_bare_name_is_never_a_path_on_any_host(self, notify, monkeypatch, name):
        for fake_sep in ("/", "\\"):
            monkeypatch.setattr(os, "sep", fake_sep)
            assert notify.looks_like_a_path(name) is False


class TestSoundResolution:
    def test_a_bare_name_resolves_against_the_system_sounds(
        self, notify, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(notify, monkeypatch, tmp_path)
        argv = notify.sound_argv("Hero")
        assert argv[0] == "afplay"
        # str(Path(...)) rather than a hardcoded "/System/..." string: on a
        # PosixPath (the real target, macOS) the separator is "/" either way,
        # but a dev box running this test under WindowsPath renders "\", and
        # the resolution logic under test is platform-agnostic, not the
        # separator convention pathlib happens to print.
        assert argv[-1] == str(notify.MAC_SOUND_DIR / "Hero.aiff")

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
        """No other platform has a named system sound set to resolve against.

        os.name is mocked alongside sys.platform: Windows resolves a bare
        name through WINDOWS_SOUNDS regardless of what sys.platform claims,
        since that table exists for a real Windows interpreter, not a
        platform label -- so simulating "neither macOS nor Windows" has to
        clear both.
        """
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(os, "name", "posix")
        assert notify.sound_argv("Hero") is None

    def test_a_windows_sound_that_is_not_on_this_machine_plays_nothing(
        self, notify, monkeypatch
    ):
        """The same guard the darwin branch has, for the same reason.

        C:\\Windows\\Media is not identical across SKUs and locales -- Server,
        N and LTSC ship subsets, and "Windows Notify Messaging.wav" is one of
        the files that can be absent. SoundPlayer.PlaySync() on a missing file
        throws into stderr this hook discards, which is indistinguishable from
        the sound being off.
        """
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setitem(
            notify.WINDOWS_SOUNDS, "Funk", r"C:\Windows\Media\NoSuchSound.wav"
        )
        assert notify.sound_argv("Funk") is None

    def test_a_windows_sound_that_is_present_still_plays(
        self, notify, monkeypatch, tmp_path
    ):
        """The other half: the check must not mute a name that does resolve."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(os, "name", "nt")
        real = tmp_path / "tada.wav"
        real.write_bytes(b"")
        monkeypatch.setitem(notify.WINDOWS_SOUNDS, "Hero", str(real))
        argv = notify.sound_argv("Hero")
        assert argv is not None
        assert str(real) in argv[-1]

    def test_the_volume_is_passed_to_the_player(self, notify, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(notify, monkeypatch, tmp_path)
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
        self,
        notify,
        monkeypatch,
        spawned,
        tmp_path,
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(notify, monkeypatch, tmp_path)
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
        """An empty sound must mute the sound only. A reason silenced down to
        no sound *and* no banner would make the knob indistinguishable from
        deleting the reason."""
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setenv("CLAUDE_NOTIFY_SOUND_DONE", "")
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert not any("afplay" in argv[0] for argv in spawned)
        assert spawned

    def test_a_parked_turn_neither_sounds_nor_banners(
        self, notify, monkeypatch, spawned, tmp_path
    ):
        """Not merely silent: no banner either, and nothing spawned at all. A
        banner per subagent round-trip is the same nag by a quieter route."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(
            notify,
            monkeypatch,
            {
                "hook_event_name": "Stop",
                "cwd": "/w/thesis",
                "background_tasks": [
                    {"id": "a1", "type": "subagent", "status": "running"}
                ],
            },
        )
        assert spawned == []

    def test_banner_off_leaves_only_the_sound(
        self, notify, monkeypatch, spawned, tmp_path
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(notify, monkeypatch, tmp_path)
        monkeypatch.setattr(notify, "BANNER", False)
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert [argv[0] for argv in spawned] == ["afplay"]

    def test_an_environment_override_wins(self, notify, monkeypatch, spawned, tmp_path):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(notify, monkeypatch, tmp_path)
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
