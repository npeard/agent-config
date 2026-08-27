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
import stat
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


def mac_sounds_present(monkeypatch):
    """Make every bare macOS sound name resolve, without a real Mac.

    The darwin branch of sound_argv() checks Path.is_file() against
    MAC_SOUND_DIR, a fixed macOS path (/System/Library/Sounds) that exists
    only on an actual Mac -- there is no Windows equivalent to point it at,
    the same gap TestStalledWatchdog's POSIX-only cases hit for mode bits and
    symlinks. Faking the check, rather than a real file, keeps every other
    assertion -- including the exact resolved path string -- intact.
    """
    monkeypatch.setattr(Path, "is_file", lambda self: True)


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
    def test_work_still_in_flight_holds_the_ping(self, notify, task):
        """Stop fires every time the main loop yields, including when it
        yields to wait on a subagent it will be woken up for. Announcing
        those is the noise this gate exists to remove."""
        payload = {"hook_event_name": "Stop", "background_tasks": [task]}
        assert notify.reason(payload) == notify.PARKED

    def test_a_continued_stop_does_not_arm_the_watchdog(self, notify):
        """stop_hook_active is a duplicate of a turn already handled, so it
        is not a fresh park and must not start a second clock."""
        payload = {
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "background_tasks": [{"id": "a1", "type": "subagent", "status": "running"}],
        }
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
            ("worker_permission_prompt", "permission"),
            ("agent_needs_input", "agent"),
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

    def test_a_notification_is_never_gated_by_background_work(self, notify):
        """A subagent blocked on the user is the one thing worth interrupting
        for, and it can only ever arrive while that subagent is in flight.
        Reusing the Stop gate here would mute it exactly when it matters."""
        payload = {
            "hook_event_name": "Notification",
            "notification_type": "agent_needs_input",
            "background_tasks": [{"id": "a1", "type": "subagent", "status": "running"}],
        }
        assert notify.reason(payload) == "agent"

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


class TestSoundResolution:
    def test_a_bare_name_resolves_against_the_system_sounds(self, notify, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
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

    def test_the_volume_is_passed_to_the_player(self, notify, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
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
        mac_sounds_present(monkeypatch)
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
        """Not merely silent: no banner either. A banner per subagent
        round-trip is the same nag by a quieter route. The watchdog it does
        spawn is a detached timer, not a notification."""
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(notify, "TMPDIR", tmp_path)
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
        assert [argv for argv in spawned if "afplay" in argv[0]] == []
        assert [argv for argv in spawned if "osascript" in argv[0]] == []
        assert [argv for argv in spawned if "--watch" in argv]

    def test_an_agent_needing_input_is_audible(self, notify, monkeypatch, spawned):
        """The promotion is the point: this reason exists to be heard, so a
        sound that resolves is part of its contract."""
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
        feed(
            notify,
            monkeypatch,
            {
                "hook_event_name": "Notification",
                "notification_type": "agent_needs_input",
                "message": "Agent is waiting on your answer",
                "cwd": "/w/thesis",
            },
        )
        assert any("afplay" in argv[0] for argv in spawned)
        assert any("waiting on your answer" in arg for argv in spawned for arg in argv)

    def test_banner_off_leaves_only_the_sound(self, notify, monkeypatch, spawned):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
        monkeypatch.setattr(notify, "BANNER", False)
        feed(notify, monkeypatch, {"hook_event_name": "Stop"})
        assert [argv[0] for argv in spawned] == ["afplay"]

    def test_an_environment_override_wins(self, notify, monkeypatch, spawned):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
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


class TestStalledWatchdog:
    """The gate above is unbounded on purpose -- a task that never finishes
    silences the turn for as long as it runs. That is only tolerable if the
    silence eventually announces itself, which is this watchdog's whole job.
    A reactive check cannot do it: a wedged job produces no events, so the
    hook is never invoked in the one case worth catching.
    """

    @pytest.fixture
    def tmp_marker(self, notify, monkeypatch, tmp_path):
        monkeypatch.setattr(notify, "TMPDIR", tmp_path)
        return tmp_path

    def prearm(self, notify):
        """An armed marker without going through arm().

        Written by hand because watch_dir() no longer creates itself: only
        arm() does, and these tests exercise the watchdog rather than the
        arming.
        """
        notify.watch_dir().mkdir(mode=0o700, exist_ok=True)
        notify.watch_path("s-1").touch()

    def parked(self):
        return {
            "hook_event_name": "Stop",
            "session_id": "s-1",
            "cwd": "/w/thesis",
            "background_tasks": [{"id": "a1", "type": "subagent", "status": "running"}],
        }

    def test_a_park_arms_a_watchdog_and_says_nothing_yet(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, self.parked())
        assert notify.watch_path("s-1").exists()
        assert [argv for argv in spawned if "afplay" in argv[0]] == []
        assert any("--watch" in argv for argv in spawned)

    def test_the_child_is_handed_exactly_what_it_unpacks(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """main() unpacks sys.argv[2:5] positionally. Reorder these and the
        child reads the pid as a session id, looks for a marker that cannot
        exist, and returns silently -- with every other test still green."""
        feed(notify, monkeypatch, self.parked())
        argv = next(a for a in spawned if "--watch" in a)
        # The child sees this list minus argv[0], so its sys.argv[1] is the
        # flag and sys.argv[2:5] is exactly the triple below.
        assert argv[1:] == [
            str(Path(notify.__file__).resolve()),
            "--watch",
            "s-1",
            str(os.getppid()),
            "thesis",
        ]

    def test_arming_twice_starts_only_one_clock(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """Otherwise every yield during a long park would restart the timer
        and stack a watchdog, and the nudge would arrive N times."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, self.parked())
        feed(notify, monkeypatch, self.parked())
        assert len([argv for argv in spawned if "--watch" in argv]) == 1

    def test_work_clearing_disarms_the_clock(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """One nudge per continuous in-flight stretch: when the work drains,
        the stretch is over and a later one deserves its own clock."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, self.parked())
        assert notify.watch_path("s-1").exists()
        feed(
            notify,
            monkeypatch,
            {"hook_event_name": "Stop", "session_id": "s-1", "background_tasks": []},
        )
        assert not notify.watch_path("s-1").exists()

    def test_a_continued_stop_still_disarms_when_work_has_drained(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """reason() returns None for a continued Stop, so keying disarm on
        the reason loses the drain whenever another blocking Stop hook is
        registered -- and the nudge then fires about finished work."""
        feed(notify, monkeypatch, self.parked())
        assert notify.watch_path("s-1").exists()
        feed(
            notify,
            monkeypatch,
            {
                "hook_event_name": "Stop",
                "session_id": "s-1",
                "stop_hook_active": True,
                "background_tasks": [],
            },
        )
        assert not notify.watch_path("s-1").exists()

    def test_a_failed_spawn_does_not_leave_a_dead_clock(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """An armed marker with no child suppresses arming for the rest of
        the session, so the feature would be off with nothing to show it."""
        monkeypatch.setattr(notify, "spawn", lambda _argv: False)
        feed(notify, monkeypatch, self.parked())
        assert not notify.watch_path("s-1").exists()

    def test_the_watchdog_nudges_while_the_park_is_still_live(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        self.prearm(notify)
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert any("Sosumi.aiff" in arg for argv in spawned for arg in argv)
        assert any("thesis" in arg for argv in spawned for arg in argv)

    def test_a_fired_nudge_does_not_come_round_again(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """Once per stretch, and a long-lived background task is one stretch
        however many turns happen during it. Deleting the marker on firing
        would let the next parked turn re-arm, turning a one-shot nudge into
        a ten-minute alarm for as long as the task lives."""
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        feed(notify, monkeypatch, self.parked())
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert len([a for a in spawned if "afplay" in a[0]]) == 1
        feed(notify, monkeypatch, self.parked())
        assert len([a for a in spawned if "--watch" in a]) == 1, "re-armed"
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert len([a for a in spawned if "afplay" in a[0]]) == 1, "nudged twice"

    def test_the_next_stretch_gets_its_own_nudge(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """The other half of "per stretch": once the work drains, a later
        long park is a new stretch and deserves to be reported."""
        monkeypatch.setattr(sys, "platform", "darwin")
        mac_sounds_present(monkeypatch)
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        feed(notify, monkeypatch, self.parked())
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        feed(
            notify,
            monkeypatch,
            {"hook_event_name": "Stop", "session_id": "s-1", "background_tasks": []},
        )
        feed(notify, monkeypatch, self.parked())
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert len([a for a in spawned if "afplay" in a[0]]) == 3, "done + 2 nudges"

    def test_a_disarmed_watchdog_stays_quiet(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert spawned == []

    def test_a_dead_session_is_not_nudged_about(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """The marker outlives a session killed mid-park. Nudging then would
        be a false alarm about a session that no longer exists."""
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        monkeypatch.setattr(notify, "alive", lambda _pid: False)
        self.prearm(notify)
        notify.watchdog("s-1", "999999", "thesis")
        assert spawned == []
        assert not notify.watch_path("s-1").exists(), "and it cleans up after itself"

    def test_a_muted_watchdog_still_releases_its_marker(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """Otherwise a muted session leaves a marker that outlives it and
        suppresses the next stretch's watchdog for a session that is gone."""
        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        monkeypatch.setenv("CLAUDE_NOTIFY_OFF", "1")
        self.prearm(notify)
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert spawned == []
        assert not notify.watch_path("s-1").exists()

    def test_a_drain_inside_the_write_window_is_not_resurrected(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """The watchdog reads the marker, then writes it. If the work drains
        in between, the hook unlinks it and a plain write recreates it as
        reported -- which announces finished work and then blocks arming for
        the rest of the session, since arm() cannot tell that marker from a
        live clock."""
        monkeypatch.setattr(sys, "platform", "darwin")
        feed(notify, monkeypatch, self.parked())
        real_alive = notify.alive

        def drain_then_answer(pid):
            notify.disarm("s-1")
            return real_alive(pid)

        monkeypatch.setattr(notify.time, "sleep", lambda _: None)
        monkeypatch.setattr(notify, "alive", drain_then_answer)
        notify.watchdog("s-1", str(os.getpid()), "thesis")
        assert not notify.watch_path("s-1").exists(), "resurrected"
        assert [a for a in spawned if "afplay" in a[0]] == [], "announced a drain"

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX mode bits and uid checks have no Windows equivalent; "
        "%TEMP% is already per-user, and notify.py skips the check there",
    )
    def test_a_lax_marker_directory_is_refused(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """mkdir(mode=...) only applies its mode when it creates, so a
        pre-created directory keeps whatever mode it was given. On a shared
        /tmp that is a co-user's directory holding our markers."""
        notify.watch_dir().mkdir(mode=0o777)
        os.chmod(notify.watch_dir(), 0o777)
        feed(notify, monkeypatch, self.parked())
        assert [a for a in spawned if "--watch" in a] == []

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX mode bits and uid checks have no Windows equivalent; "
        "%TEMP% is already per-user, and notify.py skips the check there",
    )
    def test_a_symlinked_marker_directory_is_refused(
        self, notify, monkeypatch, spawned, tmp_marker, tmp_path
    ):
        """mkdir(exist_ok=True) checks is_dir(), which follows links, so a
        link into someone else's tree is accepted as our private directory."""
        elsewhere = tmp_path / "theirs"
        elsewhere.mkdir(mode=0o700)
        notify.watch_dir().symlink_to(elsewhere)
        feed(notify, monkeypatch, self.parked())
        assert [a for a in spawned if "--watch" in a] == []
        assert list(elsewhere.iterdir()) == []

    @pytest.mark.parametrize("session", ["../escape", "a/b", "", "..", "x" * 400])
    def test_a_hostile_session_id_cannot_escape_the_marker_dir(
        self, notify, tmp_marker, session
    ):
        """session_id is payload text and it lands in a filename, so it is
        sanitized rather than trusted."""
        path = notify.watch_path(session)
        assert path.parent == notify.watch_dir(), path
        assert tmp_marker in path.parents
        assert path.name.startswith("claude-notify-")

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX mode bits and uid checks have no Windows equivalent; "
        "%TEMP% is already per-user, and notify.py skips the check there",
    )
    def test_markers_live_in_a_private_directory(
        self, notify, monkeypatch, spawned, tmp_marker
    ):
        """gettempdir() is per-user on macOS but is the shared, sticky /tmp
        on Linux. Directly in there, anyone who guessed a session id could
        pre-create the name to suppress that session's watchdog."""
        d = notify.watch_dir()
        assert not d.exists(), "computed, not created, until something arms"
        assert d.parent == tmp_marker
        feed(notify, monkeypatch, self.parked())
        assert d.is_dir()
        assert stat.S_IMODE(d.stat().st_mode) == 0o700

    @pytest.mark.skipif(
        os.name == "nt",
        reason="POSIX mode bits and uid checks have no Windows equivalent; "
        "%TEMP% is already per-user, and notify.py skips the check there",
    )
    def test_arming_refuses_to_follow_a_planted_symlink(
        self, notify, monkeypatch, spawned, tmp_marker, tmp_path
    ):
        """O_EXCL|O_CREAT fails on a symlink whose target does not exist, so
        a planted link cannot redirect the marker write."""
        target = tmp_path / "victim"
        notify.watch_dir().mkdir(mode=0o700)
        notify.watch_path("s-1").symlink_to(target)
        feed(notify, monkeypatch, self.parked())
        assert not target.exists(), "followed the link"
        assert [a for a in spawned if "--watch" in a] == [], "armed anyway"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, 600),
            ("60", 60),
            ("0", 0),
            ("-5", 0),
            ("nonsense", 600),
            ("", 600),
            # time.sleep raises OverflowError past time_t, in a child whose
            # stderr is DEVNULL -- a silent death holding an armed marker.
            ("1e30", 86400),
            ("inf", 86400),
        ],
    )
    def test_the_delay_override_is_read_in_the_waiting_process(
        self, notify, monkeypatch, raw, expected
    ):
        """Resolved in the child, not the parent: the hook exits immediately
        and the watchdog is what waits."""
        monkeypatch.delenv("CLAUDE_NOTIFY_LONG_SECONDS", raising=False)
        if raw is not None:
            monkeypatch.setenv("CLAUDE_NOTIFY_LONG_SECONDS", raw)
        assert notify.long_task_seconds() == expected

    def test_alive_never_signals_on_windows(self, notify, monkeypatch):
        """os.kill(pid, 0) does not probe on Windows -- CPython routes any
        signal other than the two console events to TerminateProcess, so the
        probe would kill the host. Absence of a probe means we nudge."""
        monkeypatch.setattr(os, "name", "nt")
        calls = []
        monkeypatch.setattr(os, "kill", lambda *a: calls.append(a))
        assert notify.alive(1) is True
        assert calls == []
