#!/usr/bin/env python3
# claude-hook: PreToolUse Bash|PowerShell
"""Deny a subagent sleep-polling for a long job.

A Bash call is capped near 590 s, so an agent waiting on an hour-long compute
with `until ...; sleep 30` wakes about every 10 minutes. Each wake finds the
prompt cache expired and rewrites the whole context at full price.

Measured: session 3ede61fe (2026-10-20), an Opus implementer, did this for
hour-long report computes. 80 turns above 100k context wrote 42.1M of its
43.3M cache-write tokens, and it peaked at 724,459 tokens over 592 turns.
Same shape: bf2b0c84 (75 turns, 12.2M) and 6ada315c (43 turns, 10.5M).

Only a subagent is denied (`agent_id` is present in its hook input): the main
session polling once is cheap, and the fix -- launch detached, return, let the
orchestrator wait -- is only available to something that has an orchestrator.
Commands are tokenized so a path, a quoted string or `grep sleep` is never
mistaken for a sleep.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

# A sibling loaded by path: hooks run from an arbitrary cwd, with no sys.path.
_spec = importlib.util.spec_from_file_location(
    "hook_lib", Path(__file__).resolve().parent / "hook_lib.py"
)
hook_lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook_lib)

# Under this a lone sleep is a pause, not a wait; the cache TTL is minutes.
POLL_SLEEP_SECONDS = 60

REASON = (
    "Do not sleep-poll from a subagent: each wake after the cache expires "
    "rewrites the whole context. Launch the job detached, record its PID, log "
    'and output path, and return "waiting on <job>, output at <path>, done '
    'when <condition>" so the orchestrator waits and dispatches a fresh agent '
    "on completion. See the compute-job-safety skill."
)

SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"})
LOOP_WORDS = frozenset({"while", "until", "for", "foreach"})
# Keywords that can precede the real command word inside a compound command.
LEADING_WORDS = frozenset({"do", "then", "else", "!"})
SLEEP_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def shell_commands(command):
    """Token lists, one per simple command; newlines separate like `;`."""
    out = []
    for line in command.splitlines():
        tokens = hook_lib.tokenize(line)
        if tokens is None:
            continue
        current = []
        for token in tokens:
            if token in SEPARATORS:
                out.append(current)
                current = []
            else:
                current.append(token)
        out.append(current)
    return [words for words in out if words]


def command_words(words):
    while words and words[0] in LEADING_WORDS:
        words = words[1:]
    return words


def sleep_seconds(words):
    """Seconds a sleep command waits, or None if `words` is not one."""
    name = words[0].lower()
    args = [w for w in words[1:] if not w.startswith("-") or w[1:2].isdigit()]
    if name == "sleep":
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", args[0]) if args else None
        # A non-numeric argument (`$N`, `infinity`) has no knowable duration; 0
        # allows it rather than risk denying ordinary work on a guess.
        return float(match[1]) * SLEEP_UNITS[match[2]] if match else 0
    if name == "start-sleep":
        flags = [w.lower() for w in words[1:] if w.startswith("-")]
        if args and re.fullmatch(r"\d+(?:\.\d+)?", args[0]):
            scale = 0.001 if any(f.startswith("-m") for f in flags) else 1
            return float(args[0]) * scale
        return 0
    return None


def polls(command):
    commands = [command_words(words) for words in shell_commands(command)]
    commands = [words for words in commands if words]
    looping = any(words[0].lower() in LOOP_WORDS for words in commands)
    for words in commands:
        seconds = sleep_seconds(words)
        if seconds is None:
            continue
        if looping or seconds >= POLL_SLEEP_SECONDS:
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
        if "agent_id" not in data or data["tool_name"] not in ("Bash", "PowerShell"):
            return
        denied = polls(data["tool_input"]["command"])
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        # Fail open: a hook that tracebacks is noisier than one that declines.
        return
    if not denied:
        return
    hook_lib.deny(REASON)


if __name__ == "__main__":
    main()
