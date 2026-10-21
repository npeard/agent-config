#!/usr/bin/env python3
# claude-hook: PreToolUse SendMessage
"""Deny resuming a subagent whose context is already large.

A resume re-reads the agent's whole context on every turn, and after a pause
the prompt cache is cold, so the whole context is written again at full
price. Past a few hundred thousand tokens a fresh agent that reads a report
file is cheaper on every turn.

Both costs were measured: workflow-orchestration examples.md cases 1
(resumes after a session-limit reset) and 2 (fix rounds resumed into one
agent).

This denies rather than advises: the rule already exists in the
orchestration skill and a resume is one message away. It only acts when the
target resolves, by id or spawn name, to a subagent transcript on disk, so a
message to `main` or any other name passes untouched -- blocking ordinary
messaging would be worse than the bug.
"""

import importlib.util
import json
import sys
from pathlib import Path

# A sibling loaded by path: hooks run from an arbitrary cwd, with no sys.path.
_spec = importlib.util.spec_from_file_location(
    "hook_lib", Path(__file__).resolve().parent / "hook_lib.py"
)
hook_lib = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook_lib)

# About one fix round above a fresh fix agent's start (one reading a report
# file starts near 50k), so past this cap fresh is cheaper on every turn. The
# single home of the number: the skill and README say "the hook's cap".
# Deliberately a constant rather than an environment knob: resuming is the
# exception.
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
    # Most lines are tool results or user turns; skip parsing them.
    if b'"usage"' not in line:
        return None
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


def _tail_lines(transcript: Path, window: int, skip: int) -> list[bytes]:
    """Lines in the last `window` bytes, leaving out the last `skip` bytes.

    The line straddling the `skip` boundary is read to its end, so a pass over
    the older bytes never loses a record that the pass over the newer ones
    dropped as a fragment.
    """
    with transcript.open("rb") as handle:
        size = handle.seek(0, 2)
        if size <= skip:
            return []
        start = max(0, size - window)
        handle.seek(start)
        data = handle.read(max(0, size - skip - start))
        if skip:
            data += handle.readline()
    lines = data.splitlines()
    # A window starting mid-file begins inside a line; that fragment is not
    # JSON and must not be mistaken for a truncated usage record.
    return lines[1:] if size > window else lines


def context_tokens(transcript: Path) -> int | None:
    """Context size at the last assistant turn, or None if none was found."""
    for window, skip in ((TAIL_BYTES, 0), (WIDE_TAIL_BYTES, TAIL_BYTES)):
        for line in reversed(_tail_lines(transcript, window, skip)):
            tokens = _usage_tokens(line)
            if tokens is not None:
                return tokens
    return None


def target_transcript(subagents: Path, to: str) -> Path | None:
    """The transcript SendMessage's `to` resolves to, by agent id or name.

    Transcripts are keyed by id; a name given at spawn lives only in the
    sibling meta file, so a resume by name would otherwise pass unchecked.
    """
    by_id = subagents / f"agent-{to}.jsonl"
    if by_id.is_file():
        return by_id
    for meta in subagents.glob("agent-*.meta.json"):
        try:
            text = meta.read_text(encoding="utf-8")
            # Parse only a meta file that can hold this name at all.
            if to not in text:
                continue
            name = json.loads(text).get("name")
        except (ValueError, OSError, AttributeError):
            continue
        if name == to:
            transcript = meta.with_name(meta.name.removesuffix(".meta.json") + ".jsonl")
            return transcript if transcript.is_file() else None
    return None


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "SendMessage":
            return
        target = target_transcript(
            Path(data["transcript_path"]).with_suffix("") / "subagents",
            data["tool_input"]["to"],
        )
        tokens = context_tokens(target) if target else None
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        # Fail open: a hook that tracebacks is noisier than one that declines.
        return
    if tokens is None or tokens <= RESUME_CAP_TOKENS:
        return
    hook_lib.deny(REASON.format(tokens=tokens, cap=RESUME_CAP_TOKENS))


if __name__ == "__main__":
    main()
