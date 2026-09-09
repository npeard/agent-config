#!/usr/bin/env python3
# claude-hook: PreToolUse Write|Edit|Bash
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
import re
import shlex
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
    "*/.codex/*",
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

# Duplicated verbatim in hooks/promotion-check.py, which needs the same
# extraction for the same reason. A hook is invoked by absolute path under
# whatever interpreter ~/.claude/settings.json names and must depend on
# nothing but the standard library, so a shared module under hooks/ is not
# available: register_hooks.py registers every hooks/*.py and a test fails on
# any file there without an event marker. Keep the two copies in step.
# Shell operators that send output into a file. The fd-prefixed forms (`2>`,
# `1>>`) tokenize as a separate "2"/"1" word followed by the operator, so they
# need no entries of their own.
REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})
# `;`, `&&` and friends end one command and start the next. Splitting on them
# keeps a read in one command from being credited to a write in another.
SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"})
# An opening heredoc: `<<EOF`, `<< "EOF"`, `<<-'EOF'`. `<<<` is a herestring
# with no body and does not match, because `<` cannot start a delimiter.
# The lookbehind is what stops `<<<` matching at its second angle bracket.
# Without it a herestring like `wc -l <<<hello` was read as opening a
# heredoc delimited by "hello", so every following command was discarded
# as body -- and a `git commit` after one went unseen.
HEREDOC = re.compile(r"(?<!<)<<-?\s*([\"\']?)([A-Za-z_][A-Za-z0-9_]*)\1")
# Every named argument is a destination.
WRITES_ITS_ARGUMENTS = frozenset({"tee"})
# The last named argument is the destination.
WRITES_ITS_LAST_ARGUMENT = frozenset({"cp", "mv", "install", "rsync"})


def without_heredocs(command: str) -> str:
    """The command with heredoc bodies removed.

    A body is data being written, not commands being run, so its text must not
    be parsed for redirections of its own. Dropping it also makes the line
    split below safe: otherwise a body line is indistinguishable from the next
    command.
    """
    lines = command.splitlines()
    kept, index = [], 0
    while index < len(lines):
        kept.append(lines[index])
        for match in HEREDOC.finditer(lines[index]):
            delimiter = match.group(2)
            index += 1
            while index < len(lines) and lines[index].strip() != delimiter:
                index += 1
        index += 1
    return "\n".join(kept)


# A native Windows path: drive letter, colon, backslash, then everything up to
# the next whitespace or shell metacharacter. Only backslashes inside a match
# are doubled below.
NATIVE_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_.\-])[A-Za-z]:\\[^\s\"'|&;<>()]*")


def with_doubled_separators(line: str) -> str:
    """The line with the backslashes inside native Windows paths doubled.

    shlex(posix=True) always treats "\\" as an escape character, which ate the
    separators out of a path like "C:\\Users\\...\\CLAUDE.md" -- so it no longer
    matched the directory it lives in, and this hook fired on the master repo's
    own files, telling the agent to promote a file it was already editing in
    place.

    Keyed on the shape of the text rather than on os.name, because os.name is
    the wrong axis: the Bash tool on Windows runs Git Bash, so a command there
    legitimately contains POSIX escapes. Doubling every backslash on Windows
    split `cp /c/a\\ b.md /c/dest/` into two bogus tokens and left `-exec rm
    {} \\;` holding a stray "\\" -- inventing a destination that was never
    written, the exact error tokenize() below declines to risk. A drive-letter
    prefix is what separates the one shape shlex cannot read from the many it
    can.
    """
    return NATIVE_WINDOWS_PATH.sub(lambda m: m.group(0).replace("\\", "\\\\"), line)


def tokenize(line: str) -> "list[str] | None":
    """Tokens for one shell line, or None if it cannot be read at all.

    No quote-recovery retry here, deliberately, and audit-owed.py does have
    one. That hook asks a yes/no question about the command verb, where a
    false positive costs one marker entry its idempotence check absorbs. This
    one lifts *paths* out of the command, so stripping an unbalanced quote
    could invent a destination that was never written and put a wrong advisory
    into context. Declining is the cheaper error here.

    Duplicated verbatim in promotion-check.py and audit-owed.py: a hook runs
    standalone under whatever interpreter ~/.claude/settings.json names,
    stdlib-only and with no sys.path manipulation, so a shared module is not
    available here.
    """
    lexer = shlex.shlex(
        with_doubled_separators(line), posix=True, punctuation_chars=True
    )
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def shell_commands(command: str) -> list[list[str]]:
    """Token lists, one per command in the shell line. [] if unparsable.

    Unparsable means an unbalanced quote, in which case nothing can be said
    about what the command writes, so declining is the honest answer.
    """
    out: list[list[str]] = []
    for line in without_heredocs(command).splitlines():
        tokens = tokenize(line)
        if tokens is None:
            # Skip this line, not the whole command. Aborting everything meant
            # one unparsable line silenced the hook for the entire invocation.
            continue
        current: list[str] = []
        for token in tokens:
            if token in SEPARATORS:
                out.append(current)
                current = []
            else:
                current.append(token)
        out.append(current)
    return out


def sed_in_place(words: list[str]) -> bool:
    """Whether a sed invocation rewrites its input files.

    Without the -i test a plain `sed 's/a/b/' file` -- a read -- would be
    treated as a write of `file`.
    """
    for word in words:
        if word.startswith("--in-place"):
            return True
        if word.startswith("-") and not word.startswith("--") and "i" in word:
            return True
    return False


def destinations(tokens: list[str]) -> list[str]:
    """Paths one command plausibly writes.

    Positions, not every path mentioned: `grep TODO CLAUDE.md > out` reads
    CLAUDE.md and writes out, and crediting both would make this fire on
    searches. Returning nothing for a command with no write position is what
    keeps read-only commands silent -- the gate and the extraction are the
    same step, so there is no second predicate to fall out of agreement with.

    Deliberately incomplete: a python or awk program in a heredoc writes files
    this cannot see. It covers the shapes sessions actually use, which is the
    difference between firing sometimes and never firing at all.
    """
    out, words, index = [], [], 0
    while index < len(tokens):
        if tokens[index] in REDIRECTS:
            if index + 1 < len(tokens):
                out.append(tokens[index + 1])
            index += 2
            continue
        words.append(tokens[index])
        index += 1
    if not words:
        return out
    name = os.path.basename(words[0])
    # A sed script (`s/a/b/`) is an argument too, but it is not a path and so
    # cannot match anything downstream; excluding it would cost more than it
    # saves.
    arguments = [word for word in words[1:] if not word.startswith("-")]
    if name in WRITES_ITS_ARGUMENTS or (name == "sed" and sed_in_place(words[1:])):
        out.extend(arguments)
    elif name in WRITES_ITS_LAST_ARGUMENT and len(arguments) >= 2:
        out.append(arguments[-1])
    return out


def written_paths(command: str, cwd) -> list[str]:
    """Every path the command plausibly writes, resolved against `cwd`.

    Resolved against the payload's cwd rather than the hook process's own,
    which is whatever directory Claude Code happened to start the hook in.
    """
    base = cwd if isinstance(cwd, str) and cwd else "."
    return [
        resolve_destination(path, base)
        for tokens in shell_commands(command)
        for path in destinations(tokens)
    ]


def resolve_destination(path: str, base: str) -> str:
    """One destination, made absolute.

    expanduser first, and that is the whole point: `>> ~/.claude/CLAUDE.md`
    was being joined onto cwd as a literal "~" directory, so realpath could
    not follow install.sh's symlink back into the master repo. The self-guard
    missed and the hook advised promoting a file already being edited here --
    exactly what canonical()'s docstring says the realpath exists to prevent.
    """
    expanded = os.path.expanduser(path)
    return expanded if os.path.isabs(expanded) else os.path.join(base, expanded)


MESSAGE = (
    "About to write prose{target}. Invoke the writing-orchestration skill "
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
    command = tool_input.get("command")
    # isinstance, not truthiness: a non-string path reaches os.path.normpath
    # and raises TypeError there instead.
    if isinstance(file_path, str) and file_path:
        # Two forms from one realpath: lowercased for the pattern tests, real
        # case for the filesystem walk in project_root. Collapsing them into
        # one is the bug that hides on a case-insensitive filesystem.
        resolved = resolve(file_path)
        if not relevant(resolved.lower()):
            return
        target = f" ({file_path})"
    elif isinstance(command, str) and command:
        # The Bash branch. Without it the hook is dead in any session told to
        # edit with sed or a heredoc rather than the Write tool, which is most
        # of them, and prose work is exactly what gets done that way.
        resolved = next(
            (
                candidate
                for candidate in map(resolve, written_paths(command, data.get("cwd")))
                if relevant(candidate.lower())
            ),
            None,
        )
        if resolved is None:
            return
        # The file is not named here, unlike the branch above. A Write
        # payload's file_path is a path the session itself asked for; a path
        # this parser lifts out of a shell command is whatever the tokenizer
        # produced, and can be an arbitrary string carrying spaces and
        # newlines. Quoting that back would put text the session did not
        # author into context, which is the injection principle 5 forbids and
        # which task-list.py has already been burned by once.
        target = ""
    else:
        return
    session = data.get("session_id")
    if session and already_fired(session, project_root(resolved)):
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": MESSAGE.format(target=target),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
