"""What several hooks share: say-once markers, a shell tokenizer, deny.

Not a hook: it carries no `# claude-hook:` marker, so the registrars skip it.
The hooks load it by path (hooks run from an arbitrary cwd, with no sys.path to
find a sibling). Stdlib only, like the hooks that load it.
"""

import hashlib
import json
import os
import re
import shlex
import tempfile
from pathlib import Path

# A native Windows path: drive letter, colon, backslash, then everything up to
# the next whitespace or shell metacharacter. Only backslashes inside a match
# are doubled below.
NATIVE_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_.\-])[A-Za-z]:\\[^\s\"'|&;<>()]*")


def tokenize(line: str) -> "list[str] | None":
    """Tokens for one shell line, or None if it cannot be read at all.

    shlex(posix=True) always treats "\\" as an escape character, which eats the
    separators out of a path like "C:\\Users\\...\\CLAUDE.md", so it no longer
    matches the directory it lives in. The backslashes inside native Windows
    paths are therefore doubled first, keyed on the shape of the text rather
    than on os.name: the Bash tool on Windows runs Git Bash, so a command there
    legitimately contains POSIX escapes, and doubling every backslash splits
    `cp /c/a\\ b.md /c/dest/` into two bogus tokens and leaves `-exec rm {} \\;`
    holding a stray "\\".

    An unbalanced quote returns None rather than a guess. A hook that lifts
    paths out of the command could otherwise invent a destination that was
    never written; audit-owed.py, which only asks about the command verb,
    retries on its own.
    """
    doubled = NATIVE_WINDOWS_PATH.sub(lambda m: m.group(0).replace("\\", "\\\\"), line)
    lexer = shlex.shlex(doubled, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def stamp_dir(name: str) -> Path:
    """Where a hook's markers live, namespaced per user.

    On POSIX the temp directory is shared, so an unnamespaced directory created
    by another user is not writable by this one -- and a guard that cannot
    write its marker re-fires on every call. Windows %TEMP% is already
    per-user and has no getuid, so the suffix is omitted there.
    """
    getuid = getattr(os, "getuid", None)
    suffix = f"-{getuid()}" if getuid else ""
    return Path(tempfile.gettempdir()) / f"{name}{suffix}"


def claim(name: str, key: str) -> bool:
    """True if `key` was not yet claimed (now it is), False if it already was.

    Best effort by design: a filesystem error returns True, so the caller
    fires. A repeat is cheaper than a missed message. O_EXCL makes test and
    claim one step; an exists()-then-touch pair double-fires when two calls
    race, which is the burst these guards exist to collapse.
    """
    directory = stamp_dir(name)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.close(
            os.open(
                directory / hashlib.sha256(key.encode()).hexdigest()[:16],
                os.O_CREAT | os.O_EXCL,
            )
        )
    except FileExistsError:
        return False
    except OSError:
        return True
    return True


def claim_for(name: str, session, agent, scope: str) -> bool:
    """True if this agent has not yet been told `scope` this session.

    The agent is in the key because a subagent's context is its own: it never
    saw what its orchestrator was told. Without a session there is nothing to
    key on, so the caller fires.
    """
    if not session:
        return True
    return claim(name, f"{session}\0{agent or ''}\0{scope}")


def deny(reason: str) -> None:
    """Print the PreToolUse output that refuses the tool call with `reason`."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
