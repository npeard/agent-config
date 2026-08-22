#!/usr/bin/env python3
# claude-hook: PostToolUse Write|Edit
import fnmatch
import json
import os
import sys


def canonical(path: str) -> str:
    """Resolved, forward-slashed, lowercased form used for all matching.

    Symlinks are resolved because install.sh links ~/.claude/CLAUDE.md and
    ~/.claude/skills/<name> into the master repo. Editing the config through
    its installed path yields a path outside MASTER_REPO, so without
    realpath the self-guard misses and the hook tells you to promote a file
    you are already editing in the master repo.

    The lowercasing is explicit rather than delegated to os.path.normcase,
    which only lowercases on Windows. Relying on it meant the lowercase
    PATTERNS below could never match the real CLAUDE.md and SKILL.md
    filenames on macOS or Linux, so the hook silently never fired for
    exactly the two file kinds it exists to catch.
    """
    return os.path.realpath(os.path.normpath(path)).replace(os.sep, "/").lower()


MASTER_REPO = canonical(os.path.expanduser("~/Documents/Projects/claude-config"))
PATTERNS = ("*/claude.md", "*/memory/*.md", "*/skills/*/skill.md")
MESSAGE = (
    "You just wrote a CLAUDE.md, memory, or skill file. Check: is this "
    "preference or skill general engineering or workflow taste that holds "
    "across projects, rather than local domain or tooling detail? If "
    "general, also add it to ~/Documents/Projects/claude-config (master "
    "CLAUDE.md or skills/) and commit there."
)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # Malformed or empty stdin: a hook that tracebacks is noisier than
        # one that declines. task-list.py guards the identical call.
        return
    if not isinstance(data, dict):
        # json.load only raises for *malformed* JSON, so a valid non-object body
        # decodes fine and then has no .get -- the rule prose-writing.py
        # documents and these two hooks broke.
        return
    # `tool_response: null` is what PostToolUse sends for a rejected or aborted
    # tool call, so `or {}` rather than a default: the key is present and None.
    tool_input = data.get("tool_input") or {}
    tool_response = data.get("tool_response") or {}
    if not isinstance(tool_input, dict) or not isinstance(tool_response, dict):
        return
    file_path = tool_input.get("file_path") or tool_response.get("filePath")
    if not file_path:
        return

    # Canonicalize before comparing: expanduser can return mixed separators
    # on Windows ("C:\Users\me/Documents/..."), and hook payloads use
    # forward slashes, so a raw startswith/fnmatch silently never matches.
    path = canonical(file_path)

    # The trailing slash matters: a bare prefix test would also swallow a
    # sibling directory like "claude-config-other".
    if path.startswith(MASTER_REPO + "/"):
        return

    # fnmatchcase, not fnmatch: both sides are already lowercased above, so
    # the platform-dependent normcase inside fnmatch would be a second,
    # invisible normalization.
    if not any(fnmatch.fnmatchcase(path, p) for p in PATTERNS):
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": MESSAGE,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
