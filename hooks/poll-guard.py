#!/usr/bin/env python3
# claude-hook: PreToolUse Bash|PowerShell
"""Deny a subagent sleep-polling for a long job.

A Bash call is capped near 590 s, so an agent waiting on an hour-long compute
with `until ...; sleep 30` wakes about every 10 minutes. Each wake finds the
prompt cache expired and rewrites the whole context at full price.

The measured case is compute-job-safety examples.md case 1.

Only a subagent is denied (`agent_id` is present in its hook input): the main
session polling once is cheap, and the fix -- launch detached, return, let the
orchestrator wait -- is only available to something that has an orchestrator.
Commands are tokenized so a path, a quoted string or `grep sleep` is never
mistaken for a sleep.

What counts as a poll: any sleep inside an unbounded loop (`while`, `until`,
PowerShell `do { } until`), or a bounded `for` whose sleeps add up to
POLL_SLEEP_SECONDS -- so a ten-try `for i in $(seq 10); ...; sleep 1` retry
passes. A bounded loop's count is read from a literal word list, `$(seq ..)` or
`{a..b}`; any other count is taken as one pass rather than guessed upward.
Known false negative: a sleep hidden inside `bash -c '...'` or `python -c` is
one quoted word to the tokenizer, so it passes (fails open).
"""

import json
import re
import sys

import hook_lib

# Under this a lone sleep is a pause, not a wait; the cache TTL is minutes.
POLL_SLEEP_SECONDS = 60

REASON = (
    "Do not sleep-poll from a subagent: each wake after the cache expires "
    "rewrites the whole context. Launch the job detached, record its PID, log "
    'and output path, and return "waiting on <job>, output at <path>, done '
    'when <condition>" so the orchestrator waits and dispatches a fresh agent '
    "on completion. See the compute-job-safety skill."
)

UNBOUNDED_LOOP_WORDS = frozenset({"while", "until"})
BOUNDED_LOOP_WORDS = frozenset({"for", "foreach"})
LITERAL_WORD = re.compile(r"[\w.:/+-]+")
SEQ = re.compile(r"\$\(\s*seq((?:\s+-?\d+){1,3})\s*\)")
BRACE_RANGE = re.compile(r"\{(-?\d+)\.\.(-?\d+)\}")
# Keywords that can precede the real command word inside a compound command.
LEADING_WORDS = frozenset({"do", "then", "else", "!"})
SLEEP_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


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


def passes(command, loop):
    """How many times the bounded loop `loop` runs, or 1 if not knowable."""
    items = loop[3:] if loop[2:3] == ["in"] else []
    if items and all(LITERAL_WORD.fullmatch(word) for word in items):
        return len(items)
    match = SEQ.search(command)
    if match:
        numbers = [int(n) for n in match[1].split()]
        # seq LAST | seq FIRST LAST | seq FIRST STEP LAST
        first = numbers[0] if len(numbers) > 1 else 1
        step = numbers[1] if len(numbers) == 3 else 1
        last = numbers[-1]
        return max(1, (last - first) // step + 1) if step > 0 else 1
    match = BRACE_RANGE.search(command)
    if match:
        return abs(int(match[2]) - int(match[1])) + 1
    return 1


def polls(command):
    commands = [
        command_words(words)
        for words in hook_lib.shell_commands(command, hook_lib.tokenize)
    ]
    commands = [words for words in commands if words]
    sleeps = [s for s in map(sleep_seconds, commands) if s is not None]
    if not sleeps:
        return False
    heads = [words[0].lower() for words in commands]
    if UNBOUNDED_LOOP_WORDS.intersection(heads):
        return True
    loops = [w for w, head in zip(commands, heads) if head in BOUNDED_LOOP_WORDS]
    if loops:
        runs = max(passes(command, loop) for loop in loops)
        return sum(sleeps) * runs >= POLL_SLEEP_SECONDS
    return max(sleeps) >= POLL_SLEEP_SECONDS


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
