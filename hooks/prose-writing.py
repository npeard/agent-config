#!/usr/bin/env python3
# claude-hook: PreToolUse Write|Edit
"""Name the writing spine when a prose file is about to be written.

The skill descriptions alone are a weak trigger for prose work, because the
task rarely announces itself as writing -- it says "tighten section 3", and
the coding spine is what gets reached for. This fires on the file instead of
on the phrasing.

PreToolUse rather than PostToolUse because the advisory is worth most before
the draft exists: afterwards it can only prompt a revision pass, which is a
strictly weaker intervention than steering the first draft.

That `additionalContext` is honoured on PreToolUse and not only on PostToolUse
was verified by hand on Claude Code 2.1.238 -- writing a scratch .tex and
seeing the text arrive as "PreToolUse:Write hook additional context" -- because
the unit tests can only assert the JSON shape, not that the host reads it. A
hook whose output is ignored reports success while being dead, which this repo
has been burned by twice; see the install.sh and register_hooks.py headers. If
a future version stops honouring it, move to PostToolUse and change
hookEventName and the test assertions together.

Fires once per session per project. A thesis editing session writes main.tex
dozens of times, and an advisory re-injected on every write costs the same
context as the useful first one while buying less each time -- which is how a
hook trains its reader to skip it.

Known limitation, unverified: if Claude Code gives a subagent the same
session_id as its orchestrator, then an orchestrator that writes one prose
file early consumes the project's single advisory, and the section-drafting
subagents that follow -- the ones actually producing prose, with none of the
orchestrator's context -- get nothing. Keying on something narrower would
reintroduce the per-write noise this guard exists to remove, so the tradeoff
is deliberate rather than settled. If subagent prose quality turns out worse
than the orchestrator's, look here first.

Path handling follows hooks/promotion-check.py: realpath and lowercase before
comparing, because this repo's own files are reachable through ~/.claude
symlinks and a raw prefix test silently never matches through one.

Depends on nothing outside the standard library, deliberately: the
interpreter that runs a hook is named in ~/.claude/settings.json, a file
outside this repo and outside its checks, so a hook that needs only the
stdlib keeps working when that file is stale.
"""

import fnmatch
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath


def forward_slashed(path) -> str:
    """One separator convention everywhere, so two paths are comparable.

    project_root used str() directly and so returned OS-native separators
    while resolve() returned forward slashes. Harmless in the product -- the
    value is only a hash key -- but it made the two functions' outputs
    incomparable, which showed up as a Windows-only test failure against
    correct code.
    """
    return str(path).replace(os.sep, "/")


def resolve(path: str) -> str:
    """Resolved and forward-slashed, with real case preserved.

    Use this whenever the result will touch the filesystem.
    """
    return forward_slashed(os.path.realpath(os.path.normpath(path)))


def canonical(path: str) -> str:
    """Resolved and lowercased: the form every pattern test uses."""
    return resolve(path).lower()


MASTER_REPO = canonical(os.path.expanduser("~/Documents/Projects/claude-config"))
SUFFIXES = (".tex", ".bib", ".md", ".txt", ".rst")

# Files that are prose-shaped but are bookkeeping or configuration. OUTLINE.md
# is deliberately absent: an outline is the argument, so writing one is prose
# work, while a task list is not.
#
# readme.md is the uncomfortable one, and the boundary is worth stating: a
# README *is* prose, and the writing-orchestration skill says so. What this
# tuple decides is narrower -- whether writing the file is a reliable signal
# that prose work is underway. It is not: most README edits add a build
# command or fix a layout list, so firing here would spend the session's one
# advisory on a mechanical edit. The skill therefore says to reach for
# humanizer on a README yourself, precisely because this hook will not.
# Matched on the stem, not the full filename, so one entry covers .md, .rst
# and .txt at once. Listing full names meant a .rst project burned its single
# advisory on README.rst while README.md was correctly ignored.
EXCLUDED_STEMS = frozenset(
    {
        "claude",
        "agents",
        "gemini",
        "readme",
        "contributing",
        "changelog",
        "history",
        "authors",
        "notice",
        "license",
        "tasks",
        "todo",
        "requirements",
    }
)

# Generated output, dependencies, agent configuration, and session-scoped
# scaffolding. `build/` matters most for these projects: a Snakemake pipeline
# writes .tex into it, and advising a rewrite of a generated file is worse
# than useless. `.claude/` matters because agent and command definitions are
# Markdown but are configuration -- advising the writing spine while someone
# authors a hook is the same noise EXCLUDED_NAMES exists to prevent.
EXCLUDED_PATHS = (
    # One level, not two: `*/skills/*/*` let a flat `skills/foo.md` through.
    "*/skills/*",
    "*/.claude/*",
    "*/memory/*",
    "*/docs/superpowers/*",
    "*/scratch/*",
    # This harness directs agents to write throwaway files to a scratchpad
    # path, so a jotted .md note there would otherwise spend the project's
    # one advisory on a file nobody will read.
    "*/scratchpad/*",
    "*/_build/*",
    "*/.github/*",
    "*/.git/*",
    "*/node_modules/*",
    "*/site-packages/*",
    "*/build/*",
    "*/.pixi/*",
    "*/.venv/*",
    "*/.tox/*",
    "*/.snakemake/*",
)

MESSAGE = (
    "About to write prose ({path}). Invoke the writing-orchestration skill "
    "for the spine -- it carries what preflight, verify and review mean when "
    "no test can assert the deliverable is correct -- and invoke the "
    "humanizer skill before returning prose you drafted. Name the audience "
    "before drafting. Do not invent a number, citation, reference, or "
    "attribution: that is the one error a reader cannot check for you."
)


def relevant(path: str) -> bool:
    if not path.endswith(SUFFIXES):
        return False
    # The trailing slash matters: a bare prefix test would also swallow a
    # sibling directory like "claude-config-other".
    if path.startswith(MASTER_REPO + "/"):
        return False
    # Asked of the platform rather than pattern-matched, because the temp
    # directory is /tmp, /private/tmp or /var/folders/... depending on the
    # machine, and prose written there is by definition throwaway.
    if path.startswith(canonical(tempfile.gettempdir()) + "/"):
        return False
    if PurePosixPath(path).stem in EXCLUDED_STEMS:
        return False
    # fnmatchcase, not fnmatch: `path` is already lowercased, so fnmatch's
    # platform-dependent normcase would be a second, invisible normalization.
    return not any(fnmatch.fnmatchcase(path, p) for p in EXCLUDED_PATHS)


def project_root(path: str) -> str:
    """The enclosing git root, else the containing directory.

    Takes the *resolved* path, never the lowercased one. Everything else here
    lowercases before matching, but this function touches the filesystem, and
    on a case-sensitive filesystem -- Linux, which pixi.toml declares -- a
    lowercased "/home/me/Projects/Thesis" does not exist, so no `.git` is ever
    found and every chapter counts as its own project. promotion-check.py gets
    away with one canonical form only because it never leaves memory.

    Keyed per project rather than per file so that editing three chapters
    produces one advisory, and per project rather than per session so that
    moving to a different repo mid-session still produces one.
    """
    start = Path(path).parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return forward_slashed(candidate)
    return forward_slashed(start)


def stamp_dir() -> Path:
    """Where the once-per-session stamps live, namespaced per user.

    On POSIX the temp directory is shared, so an unnamespaced directory
    created by another user is not writable by this one -- and a guard that
    cannot write its stamp re-fires on every single write. Windows %TEMP% is
    already per-user, and has no getuid, so the suffix is simply omitted.
    """
    getuid = getattr(os, "getuid", None)
    suffix = f"-{getuid()}" if getuid else ""
    return Path(tempfile.gettempdir()) / f"claude-prose-hook{suffix}"


def already_fired(session: str, root: str) -> bool:
    """Whether this session has already been told about this project.

    Best effort by design: any filesystem error returns False, so the
    advisory fires. A duplicate is cheaper than a miss.
    """
    digest = hashlib.sha256(f"{session}\0{root}".encode()).hexdigest()[:16]
    directory = stamp_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # O_CREAT | O_EXCL makes testing and claiming one atomic step. An
        # exists()-then-touch pair double-fires when two Write calls race,
        # which is precisely the burst this guard exists to collapse.
        os.close(os.open(directory / digest, os.O_CREAT | os.O_EXCL))
    except FileExistsError:
        return True
    except OSError:
        return False
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # A hook that tracebacks is noisier than one that declines;
        # promotion-check.py and task-list.py guard the identical call.
        return
    # json.load only raises for *malformed* JSON, so a valid non-object body
    # -- `null`, `[]`, `"str"`, `42` -- decodes fine and then has no .get.
    # Every layer below is checked for shape rather than truthiness, because
    # the docstring above promises this declines instead of tracebacking, and
    # a hook that exits non-zero on a surprising payload is worse than one
    # that stays quiet.
    if not isinstance(data, dict):
        return
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    file_path = tool_input.get("file_path")
    # isinstance, not truthiness: a non-string path reaches os.path.normpath
    # and raises TypeError there instead.
    if not isinstance(file_path, str) or not file_path:
        return
    # Two forms from one realpath: lowercased for the pattern tests, real
    # case for the filesystem walk in project_root. Collapsing them into one
    # is the bug that hides on a case-insensitive filesystem.
    resolved = resolve(file_path)
    if not relevant(resolved.lower()):
        return
    session = data.get("session_id")
    if session and already_fired(session, project_root(resolved)):
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": MESSAGE.format(path=file_path),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
