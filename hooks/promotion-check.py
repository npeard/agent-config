#!/usr/bin/env python3
# claude-hook: PostToolUse Write|Edit|Bash
import fnmatch
import json
import os
import re
import shlex
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


def tokenize(line: str) -> "list[str] | None":
    """Tokens for one shell line, or None if it cannot be read at all.

    No quote-recovery retry here, deliberately, and audit-owed.py does have
    one. That hook asks a yes/no question about the command verb, where a
    false positive costs one marker entry its idempotence check absorbs. This
    one lifts *paths* out of the command, so stripping an unbalanced quote
    could invent a destination that was never written and put a wrong advisory
    into context. Declining is the cheaper error here.

    Backslashes are doubled first on Windows because shlex(posix=True) always
    treats "\\" as a POSIX escape character, which eats the separators out of
    a native path like "C:\\Users\\...\\CLAUDE.md" -- so it no longer matched
    the directory it lives in, and this hook fired on the master repo's own
    files, telling the agent to promote a file it was already editing in
    place. Duplicated verbatim in prose-writing.py and audit-owed.py: a hook
    runs standalone under whatever interpreter ~/.claude/settings.json names,
    stdlib-only and with no sys.path manipulation, so a shared module is not
    available here.
    """
    if os.name == "nt":
        line = line.replace("\\", "\\\\")
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
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
    "You just wrote a CLAUDE.md, memory, or skill file. Check: is this "
    "preference or skill general engineering or workflow taste that holds "
    "across projects, rather than local domain or tooling detail? If "
    "general, also add it to ~/Documents/Projects/claude-config (master "
    "CLAUDE.md or skills/) and commit there."
)


def promotable(file_path: str) -> bool:
    """Whether writing this path is the promotion decision this hook asks for."""
    # Canonicalize before comparing: expanduser can return mixed separators
    # on Windows ("C:\Users\me/Documents/..."), and hook payloads use
    # forward slashes, so a raw startswith/fnmatch silently never matches.
    path = canonical(file_path)
    # The trailing slash matters: a bare prefix test would also swallow a
    # sibling directory like "claude-config-other".
    if path.startswith(MASTER_REPO + "/"):
        return False
    # fnmatchcase, not fnmatch: both sides are already lowercased above, so
    # the platform-dependent normcase inside fnmatch would be a second,
    # invisible normalization.
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in PATTERNS)


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
    command = tool_input.get("command")
    if isinstance(file_path, str) and file_path:
        candidates = [file_path]
    elif isinstance(command, str) and command:
        # The Bash branch. Registered for it because sessions are routinely
        # instructed to edit files with sed, a heredoc or a short script
        # instead of the Write and Edit tools, and in such a session a hook
        # matching only Write|Edit never fires at all -- 22 commits of exactly
        # the work this exists to catch, zero firings.
        candidates = written_paths(command, data.get("cwd"))
    else:
        return

    if not any(promotable(candidate) for candidate in candidates):
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
