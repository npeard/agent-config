#!/usr/bin/env python3
# claude-hook: Stop
# claude-hook: Notification
# claude-hook: PreToolUse AskUserQuestion
"""Play a sound (and post a banner) when the turn comes back to the user.

Replaces the `singularityinc.claude-notifier` VSCode extension, which did the
same job from five JavaScript hooks it wrote into ~/.claude/settings.json
itself. The extension worked; what it did not do was travel. Its sounds lived
in a machine-local config file that `install.sh` neither creates nor knows
about, so a new machine came up silent until someone remembered to install a
VSCode extension -- which is the same "manual step nothing verifies" failure
that `register_hooks.py` exists to remove.

Terminal-agnostic by construction, not by detection: the sound is played by
the operating system rather than by writing BEL to a tty, so a bare terminal,
the VSCode integrated terminal, tmux and an editor task all behave the same.
Nothing here asks which one it is running under, because that question is
what the extension needed to ask and what its fallback path got wrong.

Three events, one file. Splitting them would give three copies of the SOUNDS
table below, and a notifier whose per-event sounds disagree with each other is
worse than one sound for everything.

The file has a second entry point, `--watch`, which is itself re-spawned
detached to wait out the stalled-work nudge. It lives here rather than in a
sibling script for the same reason the three events do: it needs the same
SOUNDS table, the same player resolution and the same banner logic, and a
watchdog whose sounds had drifted from the notifier's would be worse than no
watchdog.

Depends on nothing outside the standard library, deliberately -- see the same
note in hooks/prose-writing.py: the interpreter that runs a hook is named in
~/.claude/settings.json, a file outside this repo and outside its checks.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --------------------------------------------------------------------------
# Customization. Edit these; they are the point of the hook being code, and
# they are version-controlled, so a new machine sounds like this one. For a
# single session instead, the environment wins: CLAUDE_NOTIFY_OFF=1 mutes
# everything, CLAUDE_NOTIFY_SOUND_DONE=Tink overrides one reason, and
# CLAUDE_NOTIFY_LONG_SECONDS=60 tightens the stalled-work nudge below.
# --------------------------------------------------------------------------

# Sound per reason. On macOS a bare name resolves to
# /System/Library/Sounds/<name>.aiff (Basso, Blow, Bottle, Frog, Funk, Glass,
# Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine, Tink); anything containing
# a path separator is used as a path, so a custom .aiff or .wav works
# anywhere. An empty string silences that reason while leaving the knob
# visible -- deleting the key would make the reason look unsupported.
SOUNDS = {
    "done": "Hero",
    "permission": "Glass",
    "question": "Funk",
    # A background agent blocked on an answer. Distinct from `permission`
    # because the two want different things from you: permission is one
    # keystroke about a tool call you are already watching, this is a
    # subagent stalled until you go and read what it asked.
    "agent": "Submarine",
    # The background-work gate below is unbounded on purpose, so this is the
    # sound of it admitting that. Deliberately unlike the other three: it is
    # the only one that means "something may be wrong" rather than "your
    # turn".
    "stalled": "Sosumi",
}

# How long background work may hold the "finished" ping before the hook says
# so, once. The gate below has no upper bound -- a task that never finishes
# silences the turn for as long as it runs -- and an unbounded silence is
# indistinguishable from a broken hook. This is what makes it distinguishable.
LONG_TASK_SECONDS = 600

# Ceiling on the override below. time.sleep raises OverflowError past the
# platform's time_t, and it would raise it inside the detached child whose
# stderr goes to DEVNULL -- a silent death still holding an armed marker,
# which switches the feature off for the rest of the session with nothing to
# show why. A day is longer than any delay worth waiting for anyway.
LONG_TASK_CEILING = 86400

# afplay's -v is a linear multiplier, so 1.0 is the file's own level and
# values above 1 amplify. Ignored on platforms whose player takes no volume.
VOLUME = 1.0

# Desktop banner alongside the sound. The sound says "your turn"; the banner
# says which project, which is what matters when several sessions run at once.
BANNER = True

# --------------------------------------------------------------------------

# Which `Notification` types mean the turn is the user's. The event also
# carries progress and housekeeping types (auth_success, quota_auto_resume_*,
# computer_use_*, elicitation_*, push_notification) that need no answer, and
# pinging on those trains the ear to ignore the ping.
#
# Claude Code matches a Notification hook's `matcher` against this same
# notification_type, so this filter could have lived in settings.json
# instead. It lives here because settings.json is generated by
# register_hooks.py from the marker above and cannot be seen from this file:
# a filter split across the two would drift silently.
NOTIFICATION_REASONS = {
    "permission_prompt": "permission",
    "worker_permission_prompt": "permission",
    "agent_needs_input": "agent",
    # `idle_prompt` is deliberately absent rather than mapped to a silent
    # reason. A prompt sitting open is not news: whatever turn left it open
    # was announced when it ended, so this can only be a second ping for
    # something already reported. Silencing it still cost a banner per idle
    # stretch, which is the same nag by a quieter route.
}

# Banner text for reasons the host does not describe itself. Notification
# supplies its own `message` ("Claude needs your permission to use Bash"),
# which is more specific than anything written here, so permission and agent
# only fall back to these.
MESSAGES = {
    "done": "Finished -- your turn",
    "question": "Waiting on your answer",
    "permission": "Needs your permission",
    "agent": "A background agent needs your input",
    "stalled": "Background work still running -- expected, or stuck?",
}

# Where the watchdog marker lives. A module constant so a test can point it
# somewhere it owns rather than writing into the real temp directory.
TMPDIR = Path(tempfile.gettempdir())

# reason() returns this instead of a SOUNDS key when the turn ended only
# because it is waiting on background work. Distinct from None, which means
# "nothing to say": a park says nothing *now* but starts the clock below.
PARKED = "parked"

# Written into the marker once the nudge has been said. The marker cannot
# simply be deleted at that point: arm() treats an absent marker as "no clock
# running", so the next parked turn would start another one and the one-shot
# nudge would become a ten-minute alarm for as long as the task lives.
NUDGED = "nudged"

# Bare names resolve against the platform's own sound set. macOS has one at
# a known path; Windows does not, so each SOUNDS entry's macOS name is mapped
# to a file that ships in C:\Windows\Media rather than left unresolvable --
# which is why every ping was silent there. Keyed by SOUNDS' *values*, not
# its roles: sound_argv() below only ever sees the resolved name ("Hero"),
# never which role ("done") asked for it -- the same string an environment
# override like CLAUDE_NOTIFY_SOUND_DONE could substitute.
WINDOWS_SOUNDS = {
    SOUNDS["done"]: r"C:\Windows\Media\tada.wav",
    SOUNDS["permission"]: r"C:\Windows\Media\Windows Notify.wav",
    SOUNDS["question"]: r"C:\Windows\Media\Windows Ding.wav",
    SOUNDS["agent"]: r"C:\Windows\Media\Windows Notify Messaging.wav",
    SOUNDS["stalled"]: r"C:\Windows\Media\Windows Exclamation.wav",
}

MAC_SOUND_DIR = Path("/System/Library/Sounds")
# Absolute paths rather than a PATH lookup, because a hook inherits whatever
# environment the host had and Homebrew's bin is often not on it.
TERMINAL_NOTIFIER = (
    "/opt/homebrew/bin/terminal-notifier",
    "/usr/local/bin/terminal-notifier",
)


def reason(data):
    """Which SOUNDS key this payload deserves, or None to stay quiet."""
    event = data.get("hook_event_name")
    if event == "Stop":
        # A Stop hook that fed something back to the model gets Stop again
        # when the model stops a second time. The turn was already announced
        # on the first pass, so this one is a duplicate.
        if data.get("stop_hook_active"):
            return None
        # Stop fires whenever the main loop yields, not only when the work is
        # done: a turn that dispatched background subagents ends here too and
        # is woken by each one that reports, so announcing those yields is one
        # ping per round-trip for a task nobody has finished. The host draws
        # the distinction for us -- this field is in-flight background work,
        # "empty array when nothing is in flight" -- so truthiness is the
        # whole test. Absence is not emptiness: the field is optional in that
        # schema, and reading a missing key as "something is running" would
        # mute every turn on a host that omits it.
        if data.get("background_tasks"):
            return PARKED
        return "done"
    if event == "Notification":
        return NOTIFICATION_REASONS.get(data.get("notification_type"))
    if event == "PreToolUse":
        # The matcher in settings.json already narrows this, but a hook that
        # depends on a file it cannot read for correctness is a hook that
        # misfires the day that file is edited by hand.
        tool = data.get("tool_name")
        return "question" if tool == "AskUserQuestion" else None
    return None


def muted():
    """Whether this process should stay silent.

    Presence, not value: any non-empty CLAUDE_NOTIFY_OFF mutes. The one-off
    case -- `CLAUDE_NOTIFY_OFF=1 claude` for a session in a quiet room -- is
    the whole point, and a truth-y string parser here would only introduce a
    disagreement about what "0" means.
    """
    return bool(os.environ.get("CLAUDE_NOTIFY_OFF"))


def sound_for(which):
    """The configured sound name for a reason, environment first."""
    return os.environ.get(f"CLAUDE_NOTIFY_SOUND_{which.upper()}", SOUNDS.get(which, ""))


def sound_argv(name):
    """Player command for a sound name, or None if there is nothing to play."""
    if not name:
        return None
    path = name if ("/" in name or os.sep in name) else None
    if sys.platform == "darwin":
        if path is None:
            candidate = MAC_SOUND_DIR / f"{name}.aiff"
            # A name that does not resolve plays nothing rather than making
            # afplay fail invisibly, which looks identical to "sound is off".
            if not candidate.is_file():
                return None
            path = str(candidate)
        return ["afplay", "-v", str(VOLUME), path]
    if path is None and os.name == "nt":
        # Windows has no named system sound set either, but the handful of
        # macOS names SOUNDS actually uses are known ahead of time, so they
        # resolve through this table instead of a filesystem lookup like
        # macOS's.
        path = WINDOWS_SOUNDS.get(name)
    if path is None:
        # Nothing left to resolve against: a name absent from both tables
        # plays nothing rather than handing the player a path that does not
        # exist, which fails invisibly -- the same reasoning as the darwin
        # branch above.
        return None
    if os.name == "nt":
        # PowerShell single-quoted strings escape ' by doubling it; nothing
        # else is special inside them, so this is the whole escaping rule.
        quoted = path.replace("'", "''")
        return [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(New-Object Media.SoundPlayer '{quoted}').PlaySync()",
        ]
    for player in ("paplay", "aplay"):
        found = shutil.which(player)
        if found:
            return [found, path]
    return None


def banner_argv(title, message):
    """Desktop notification command, or None where there is no notifier."""
    if sys.platform == "darwin":
        for candidate in TERMINAL_NOTIFIER:
            if os.access(candidate, os.X_OK):
                # Preferred when present: osascript banners are attributed to
                # Script Editor and are dropped silently if that app has no
                # notification permission.
                return [candidate, "-title", title, "-message", message]
        # AppleScript string literals escape only backslash and quote.
        script = f'display notification "{applescript(message)}" with title "{applescript(title)}"'
        return ["osascript", "-e", script]
    notify_send = shutil.which("notify-send")
    if notify_send:
        return [notify_send, "--app-name=Claude Code", title, message]
    return None


def applescript(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def project(data):
    """Directory name of the session's cwd, or "Claude Code" if unknown.

    The name, not the path: it is a banner title, and several sessions are
    told apart by which project they are in.
    """
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return "Claude Code"
    return os.path.basename(os.path.normpath(cwd)) or "Claude Code"


def spawn(argv):
    """Start a command and do not wait for it.

    A Stop hook runs while the user is looking at the prompt, so waiting out
    a one-second sound would add a one-second pause to every turn.
    start_new_session detaches the child from this process group so the sound
    survives the hook exiting; it is accepted and ignored on Windows, so no
    platform branch is needed here.

    Returns whether anything started. Only arm() looks: a sound that failed
    to play is not worth reacting to, but a watchdog that failed to start
    means the marker it left behind has to be taken back.
    """
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        # A missing player is not worth failing a turn over, and a hook that
        # writes to stderr writes into the session transcript.
        return False
    return True


def long_task_seconds():
    """The nudge delay, environment first.

    A separate reader rather than a module constant read at import, because
    the watchdog is a separate process: this is the one knob whose value has
    to be resolved in the child that waits, not in the hook that spawned it.
    """
    raw = os.environ.get("CLAUDE_NOTIFY_LONG_SECONDS")
    if raw is None:
        return LONG_TASK_SECONDS
    try:
        return min(LONG_TASK_CEILING, max(0.0, float(raw)))
    except ValueError:
        # An unparsable override falls back rather than crashing the only
        # process that would ever have reported the stall.
        return LONG_TASK_SECONDS


def watch_dir():
    """Private directory the markers live in. Computed, not created.

    Not the temp directory itself: gettempdir() is per-user on macOS but is
    the shared, sticky /tmp on Linux, and a marker sitting directly in there
    is one that anybody who guessed a session id could pre-create to
    suppress that session's watchdog. 0700 under this user's own name
    removes the guess and the shared directory in one step.

    Only arm() creates it. Doing that here would put a mkdir behind every
    path lookup, including the disarm that now runs on every finished turn,
    and would make a function that answers "where" also mean "make sure".
    """
    uid = getattr(os, "getuid", lambda: "shared")()
    return TMPDIR / f"claude-notify-{uid}"


def ensure_watch_dir():
    """Create the marker directory, or return None if it is not ours.

    mkdir alone does not establish this. `mode=` applies only when mkdir
    actually creates, so a pre-existing directory keeps whatever mode it was
    given; and `exist_ok=True` accepts anything `is_dir()` accepts, which
    follows symlinks. On Linux's shared, sticky /tmp either is enough for a
    co-user to pre-create the name -- lax-moded, or as a link into their own
    tree -- and be handed every marker this hook writes.

    So the mkdir is exclusive, and an existing directory is checked with
    lstat, which a symlink cannot satisfy. Failing means no watchdog: it is
    a convenience, and declining to arm is cheaper than trusting a directory
    that might not be ours.
    """
    path = watch_dir()
    try:
        path.mkdir(mode=0o700, exist_ok=False)
        return path
    except FileExistsError:
        pass
    except OSError:
        return None
    try:
        info = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        return None
    if os.name != "nt":
        # Windows reports neither a meaningful uid nor POSIX mode bits, so
        # these two would reject every directory there.
        if info.st_uid != os.getuid():
            return None
        if info.st_mode & 0o077:
            return None
    return path


def watch_path(session):
    """Marker whose existence means a watchdog is already armed.

    `session_id` is payload text and it lands in a filename, so it is
    sanitized rather than trusted: alphanumerics and the two safe
    punctuation marks only, which leaves no separator and no `..` to walk
    out of the temp directory with, and a length cap so a hostile id cannot
    blow the filesystem's name limit and turn this into an error path.
    """
    safe = "".join(c for c in str(session) if c.isalnum() or c in "-_")[:64]
    return watch_dir() / f"claude-notify-{safe or 'unknown'}.watch"


def alive(pid):
    """Whether the host that armed the watchdog is still running.

    Signal 0 is the standard liveness probe on POSIX, but os.kill on Windows
    routes anything other than the two console events to TerminateProcess --
    so the probe would kill the very process it is asking about. There is no
    cheap stdlib equivalent, so Windows skips the check and accepts a
    possible nudge about a session that already exited: a spurious banner is
    a far better failure than killing the host.
    """
    if os.name == "nt":
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (OSError, ValueError):
        # Alive but not ours (PermissionError), or an unusable pid. Neither
        # is evidence of death, and nudging is the recoverable direction.
        pass
    return True


def disarm(session):
    """End the stretch, so a later one gets its own clock."""
    try:
        watch_path(session).unlink(missing_ok=True)
    except OSError:
        pass


def arm(data):
    """Start the clock on a park, unless one is already running.

    Once per continuous in-flight stretch: every yield during a long park
    reaches here, and re-arming on each would both restart the timer and
    stack a watchdog, so the nudge would arrive once per yield.
    """
    session = data.get("session_id")
    if ensure_watch_dir() is None:
        return
    try:
        # O_EXCL rather than exists()-then-touch: it makes arming atomic, so
        # two yields racing cannot both win, and it refuses to follow a
        # symlink planted at the marker's name.
        os.close(
            os.open(watch_path(session), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        )
    except FileExistsError:
        # A clock is already running for this stretch, or it has already
        # reported. Either way this turn is not a fresh park.
        return
    except OSError:
        # No marker means no watchdog rather than a crashed hook.
        return
    # The parent is the host process, and the watchdog outlives this one by
    # ten minutes, so it has to ask separately whether that host is still
    # there. argv rather than a shell command line, so none of this is
    # interpreted by anything.
    if not spawn(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--watch",
            str(session),
            str(os.getppid()),
            project(data),
        ]
    ):
        # An armed marker with no child behind it would suppress arming for
        # the rest of the session, leaving the feature off with nothing to
        # show that it is.
        disarm(session)


def watchdog(session, pid, title):
    """Say once, after a wait, that background work is still holding the ping.

    Spawned detached rather than computed at hook time because the hook only
    runs when the host invokes it: a park on a subagent produces one Stop and
    then nothing until that subagent reports, so a wedged job -- the one case
    worth catching -- generates no event to react to.
    """
    time.sleep(long_task_seconds())
    marker = watch_path(session)
    try:
        reported = marker.read_text(encoding="utf-8").strip() == NUDGED
    except OSError:
        # The work drained and some later turn disarmed us.
        return
    if reported:
        return
    if not alive(pid) or muted():
        # Nothing to say, and the marker would otherwise outlive the session
        # it describes and suppress the next stretch's watchdog.
        disarm(session)
        return
    # No O_CREAT, so this fails rather than recreating a marker that the
    # work draining removed between the read above and here. write_text
    # would have brought it back as reported, which announces a turn that
    # just finished and then blocks arming for the rest of the session,
    # because arm() cannot tell that marker from a live clock. O_NOFOLLOW
    # for the same reason the directory is lstat-ed; it is POSIX-only.
    flags = os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags)
    except OSError:
        return
    try:
        os.write(fd, NUDGED.encode())
    finally:
        os.close(fd)
    announce("stalled", title, MESSAGES["stalled"])


def announce(which, title, message):
    argv = sound_argv(sound_for(which))
    if argv:
        spawn(argv)
    if not BANNER:
        return
    argv = banner_argv(title, message)
    if argv:
        spawn(argv)


def main():
    if sys.argv[1:2] == ["--watch"]:
        session, pid, title = (sys.argv[2:5] + ["", "", ""])[:3]
        watchdog(session, pid, title or "Claude Code")
        return
    if muted():
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # Malformed stdin declines rather than tracebacks, as in
        # hooks/promotion-check.py and hooks/prose-writing.py.
        return
    # A valid non-object body ("null", "[]", "42") decodes fine and then has
    # no .get, so shape is checked rather than truthiness.
    if not isinstance(data, dict):
        return

    # Keyed on the payload rather than on the reason below, because reason()
    # collapses every continued Stop to None: with any other blocking Stop
    # hook registered, the Stop that reports the drained registry arrives as
    # a continued one, and a stretch that ended would still get nudged about.
    if data.get("hook_event_name") == "Stop" and not data.get("background_tasks"):
        disarm(data.get("session_id"))

    which = reason(data)
    if which == PARKED:
        arm(data)
        return
    if which is None:
        return

    message = data.get("message") if which in ("permission", "agent") else None
    if not isinstance(message, str) or not message:
        message = MESSAGES.get(which, "Your turn")
    announce(which, project(data), message)


if __name__ == "__main__":
    main()
