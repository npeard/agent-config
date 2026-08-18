#!/usr/bin/env python3
import fnmatch
import json
import os
import sys

MASTER_REPO = os.path.normcase(
    os.path.normpath(os.path.expanduser("~/Documents/Projects/claude-config"))
)
# Lowercase: paths are normcase'd before matching, which lowercases on
# Windows. fnmatch is case-insensitive there anyway, but matching lower
# against lower is correct on POSIX too.
PATTERNS = ("*/claude.md", "*/memory/*.md", "*/skills/*/skill.md")
MESSAGE = (
    "You just wrote a CLAUDE.md, memory, or skill file. Check: is this "
    "preference or skill general engineering or workflow taste that holds "
    "across projects, rather than local domain or tooling detail? If "
    "general, also add it to ~/Documents/Projects/claude-config (master "
    "CLAUDE.md or skills/) and commit there."
)


def main():
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    file_path = tool_input.get("file_path") or tool_response.get("filePath")
    if not file_path:
        return

    # Normalize before comparing: expanduser can return mixed separators on
    # Windows ("C:\Users\me/Documents/..."), and hook payloads use forward
    # slashes, so a raw startswith/fnmatch silently never matches.
    normalized = os.path.normcase(os.path.normpath(file_path))
    if normalized.startswith(MASTER_REPO + os.sep):
        return

    posix_path = normalized.replace(os.sep, "/")
    if not any(fnmatch.fnmatch(posix_path, p) for p in PATTERNS):
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
