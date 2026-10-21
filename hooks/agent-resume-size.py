#!/usr/bin/env python3
# claude-hook: PreToolUse SendMessage
"""Deny resuming a subagent whose context is already large.

A resume re-reads the agent's whole context on every turn, and after a pause
the prompt cache is cold, so the whole context is written again at full
price. Past a few hundred thousand tokens a fresh agent that reads a report
file is cheaper on every turn.

Measured: one implementer ran 44k -> 366k tokens in its first run, then grew
about +100k per resumed fix round across three rounds and one ad-hoc "one
more addition" (+103k). The user stopped it at 724k ("700k tokens in 1
minute?"). Separately, four resumes after a session-limit reset found a cold
cache and rewrote 373k, 516k, 610k and 722k tokens.

This denies rather than advises: the rule already exists in the
orchestration skill and a resume is one message away. It only acts when the
target resolves to a subagent transcript on disk, so a message to `main` or a
teammate name passes untouched -- blocking ordinary messaging would be worse
than the bug.
"""

import json
import sys
from pathlib import Path

# 150k allows about one fix round. The incident's implementer was 366k after
# its first run alone, and a fresh fix agent reading a report file starts near
# 50k, so past this cap fresh is cheaper on every turn. Deliberately a
# constant rather than an environment knob: resuming is the exception.
RESUME_CAP_TOKENS = 150_000

# Transcripts reach tens of MB; the last assistant turn is within the final
# few lines. If a long tool result pushes it out of the first window, one
# wider read is enough -- beyond that, fail open rather than scan the file.
TAIL_BYTES = 256 * 1024
WIDE_TAIL_BYTES = 4 * 1024 * 1024

REASON = (
    "This agent's context is {tokens:,} tokens, over the {cap:,} resume cap. "
    "Resuming re-reads all of it every turn, and after a pause it is written "
    "again cold. Dispatch a fresh agent instead: give it the previous "
    "agent's report file, the fix list, and the diff range."
)


def _usage_tokens(line: bytes) -> int | None:
    try:
        entry = json.loads(line)
        usage = entry["message"]["usage"]
        # A session limit appends a "<synthetic>" assistant turn with all-zero
        # usage after the real last turn. Reading it as 0 would wave through
        # exactly the cold-cache resume this hook exists to stop.
        if (
            entry["type"] != "assistant"
            or entry["message"].get("model") == "<synthetic>"
        ):
            return None
        tokens = sum(
            usage.get(key, 0)
            for key in (
                "input_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        )
        return tokens or None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def _tail_lines(transcript: Path, window: int) -> list[bytes]:
    with transcript.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - window))
        data = handle.read()
    lines = data.splitlines()
    # A window starting mid-file begins inside a line; that fragment is not
    # JSON and must not be mistaken for a truncated usage record.
    return lines[1:] if size > window else lines


def context_tokens(transcript: Path) -> int | None:
    """Context size at the last assistant turn, or None if none was found."""
    for window in (TAIL_BYTES, WIDE_TAIL_BYTES):
        for line in reversed(_tail_lines(transcript, window)):
            tokens = _usage_tokens(line)
            if tokens is not None:
                return tokens
    return None


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "SendMessage":
            return
        to = data["tool_input"]["to"]
        target = (
            Path(data["transcript_path"]).with_suffix("")
            / "subagents"
            / f"agent-{to}.jsonl"
        )
        tokens = context_tokens(target) if target.is_file() else None
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        # Fail open: a hook that tracebacks is noisier than one that declines.
        return
    if tokens is None or tokens <= RESUME_CAP_TOKENS:
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON.format(
                        tokens=tokens, cap=RESUME_CAP_TOKENS
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
