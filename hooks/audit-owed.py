#!/usr/bin/env python3
# claude-hook: PostToolUse Bash
"""Record that a config audit is owed, so the obligation outlives the session.

A per-commit audit was the obvious design and the wrong one. friction-ledger
exists because a loop that fires every time gets skimmed, and an audit that
ran on all eight commits of a branch would report the same nine findings
eight times. So this notices every commit and asks for one audit, at the end.

The marker file rather than a message is the point. A reminder in context is
lost to compaction, to session end, or to a fresh checkout of the branch; a
file on disk is still there tomorrow, and preflight reports it to whichever
session comes next.

Scoped to this repo. Auditing an arbitrary project's config is a different
job with different principles, and promotion-check.py already covers the
"you wrote a skill somewhere else" case.
"""

import json
import os
import re
import shlex
import subprocess
import sys


def master_repo() -> str:
    """Where this config lives, resolved.

    CLAUDE_CONFIG_REPO wins when set. The default is the path the README's
    install instructions use, but hardcoding only that makes the hook dead
    for anyone who cloned elsewhere -- and makes a test's HOME patch the only
    way to point it somewhere else, which is an unreliable thing to depend on.
    """
    override = os.environ.get("CLAUDE_CONFIG_REPO")
    # expanduser wraps the whole expression: applied only to the default, a
    # CLAUDE_CONFIG_REPO of "~/Documents/Projects/claude-config" -- the form the
    # README's own install path invites -- resolves to a literal "~" directory
    # and the hook silently never fires.
    return os.path.realpath(
        os.path.expanduser(override or "~/Documents/Projects/claude-config")
    )


MARKER = ".audit-owed"
CONFIG_PREFIXES = ("skills/", "scripts/", "hooks/")
CONFIG_FILES = ("CLAUDE.md",)

# git's own options, before the subcommand. The two-argument ones must be
# skipped as pairs or `git -C commit` would read its path argument as the
# subcommand and a real `git -C <path> commit` would be missed.
GIT_OPTIONS_WITH_VALUE = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--config-env",
    }
)
# `;`, `&&` and friends end one command and start another. Newlines are handled
# by splitting into lines first, because shlex treats a newline as ordinary
# whitespace and would run two lines together into a single command.
SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"})
# An opening heredoc: `<<EOF`, `<< "EOF"`, `<<-'EOF'`. `<<<` is a herestring
# with no body, and does not match because `<` is not a valid delimiter start.
HEREDOC = re.compile(r"<<-?\s*([\"\']?)([A-Za-z_][A-Za-z0-9_]*)\1")


def is_config_asset(path: str) -> bool:
    return path.startswith(CONFIG_PREFIXES) or path in CONFIG_FILES


def without_heredocs(command: str) -> str:
    """The command with heredoc bodies removed.

    A heredoc body is data being written, not commands being run, so a file
    whose text happens to contain `git commit` must not read as a commit.
    Dropping the bodies also makes the line split below safe: without it, a
    body line is indistinguishable from the next command.
    """
    lines = command.splitlines()
    kept, i = [], 0
    while i < len(lines):
        kept.append(lines[i])
        for match in HEREDOC.finditer(lines[i]):
            delimiter = match.group(2)
            i += 1
            while i < len(lines) and lines[i].strip() != delimiter:
                i += 1
        i += 1
    return "\n".join(kept)


def shell_commands(command: str) -> list[list[str]]:
    """Token lists, one per command in the shell line. [] if unparsable.

    Unparsable means an unbalanced quote, which is not a commit either, so
    declining is both safe and correct.
    """
    out: list[list[str]] = []
    for line in without_heredocs(command).splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            return []
        current: list[str] = []
        for token in tokens:
            if token in SEPARATORS:
                out.append(current)
                current = []
            else:
                current.append(token)
        out.append(current)
    return out


def is_commit(tokens: list[str]) -> bool:
    """Whether one command is a `git commit` that would create a commit."""
    if not tokens or os.path.basename(tokens[0]) != "git":
        return False
    args = tokens[1:]
    index = 0
    while index < len(args):
        if args[index] in GIT_OPTIONS_WITH_VALUE:
            index += 2
        elif args[index].startswith("-"):
            index += 1
        else:
            break
    if index >= len(args) or args[index] != "commit":
        return False
    # --dry-run reports what would be committed and writes nothing, so HEAD is
    # still the previous commit and recording an obligation from it is wrong.
    return "--dry-run" not in args[index + 1 :]


def commits(command: str) -> bool:
    """Whether the command actually invokes `git commit`.

    The substring test this replaces treated `git log --grep="git commit"`,
    `git commit --dry-run` and any heredoc quoting the phrase as commits. That
    matters most right after `pixi run audit --clear-owed`: on a branch whose
    HEAD touched an asset, one such command recreated the standing warning
    with nothing having been committed. It was also too narrow in the other
    direction -- `git -C <path> commit` contains no such substring.
    """
    return any(is_commit(tokens) for tokens in shell_commands(command))


def failed(response) -> bool:
    """True only when the payload positively says the command failed.

    This is the whole success guard, and it is deliberately incomplete. The
    Bash payload carries stdout/stderr/interrupted and no exit status, so a
    pre-commit rejection is invisible here. Two git-based proxies were tried
    and both were wrong: "is the index clean" suppressed a path-limited commit
    that had genuinely landed an asset, and "is the asset still staged" cost a
    third subprocess -- three git calls at five seconds each against the ten
    second budget register_hooks.py writes, so the hook could be killed
    mid-run.

    What is left unguarded is bounded and cheap: on a failed commit HEAD is the
    *previous* commit, whose assets the idempotence check below has already
    recorded, so nothing is emitted. The single exception is a branch's
    first-ever commit failing, which records one line in a gitignored marker
    that `pixi run audit --clear-owed` removes. That is a better trade than a
    proxy wrong in a new way each round.

    An earlier version also looked for `exit_code`/`is_error`, which are
    transcript fields rather than hook-payload ones, so that guard was inert.
    `interrupted` is the one failure the payload does report.
    """
    return bool(isinstance(response, dict) and response.get("interrupted"))


def checkout_and_branch(cwd: str) -> tuple[str, str]:
    """(main checkout, branch) for the repo containing cwd, or ("", "").

    The main checkout, not the toplevel: `git worktree add ../wt` puts the
    working copy outside the main one, so comparing the raw cwd against the
    master repo's path failed and the hook went silent -- on exactly the
    parallel-phase branches CLAUDE.md recommends worktrees for, which are the
    ones most likely to be changing config assets. `--git-common-dir` is the
    mapping back: it names the main checkout's .git for a worktree and the
    local one otherwise.

    Both facts come from one `git rev-parse`, which is not tidiness. Two git
    calls at four seconds fit inside the ten second timeout
    register_hooks.py writes for every hook, and committed_paths() below
    spends one of them; a third would put the hook over budget and Claude
    Code would kill it before any of these graceful fallbacks could run.
    """
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return "", ""
    lines = out.stdout.splitlines()
    if len(lines) != 2:
        return "", ""
    # rev-parse reports --git-common-dir relative to its own working
    # directory, so it comes back as a bare ".git" from a toplevel and as an
    # absolute path from a worktree. join handles both: an absolute second
    # argument wins. Asking for --path-format=absolute instead would need
    # git 2.31.
    common = os.path.realpath(os.path.join(cwd, lines[0]))
    return os.path.dirname(common), lines[1].strip()


def committed_paths(repo: str) -> list[str]:
    """Paths in HEAD's commit.

    PostToolUse means the commit already happened, so the staged set is gone
    and HEAD is what was recorded. Failures return empty rather than raising:
    a hook that tracebacks is noisier than one that declines. `git commit`
    appearing in a command is not proof a commit succeeded either; `failed`
    above is what guards that, since HEAD would otherwise be the *previous*
    commit.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                repo,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                # --root: a parentless commit otherwise reports no paths at
                # all. -m: nor does a merge commit, and a merge is how config
                # assets usually arrive on the default branch.
                "--root",
                "-m",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
            # Under the 10s timeout register_hooks.py writes for every hook.
            # At 20s Claude Code kills the hook first and the graceful
            # `return []` below is unreachable.
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> None:
    repo = master_repo()
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # Malformed or empty stdin: promotion-check.py guards the identical
        # call for the same reason.
        return
    if not isinstance(data, dict):
        return

    command = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or not commits(command):
        return

    if failed(data.get("tool_response")):
        return

    # Where the commit happened. Without this the hook judged any `git commit`
    # anywhere against the master repo's HEAD, so a commit in an unrelated
    # project re-armed the obligation -- defeating --clear-owed -- and a commit
    # in a worktree was recorded under the main checkout's branch. A rewrite
    # dropped this guard and three tests kept passing, because they only ever
    # asserted silence and the master repo's HEAD had no config asset in it.
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return
    # Realpath first: install.sh symlinks this repo into ~/.claude, so a
    # session can hold a path that resolves here without looking like it.
    resolved = os.path.realpath(cwd)
    # The comparison is on the main checkout rather than on the cwd itself, so
    # a sibling worktree of this repo is recognized as this repo. A cwd that is
    # not a git repo at all yields "" and declines: no commit happened there.
    # The trailing separator stops a bare prefix test from also swallowing a
    # sibling directory like "claude-config-other", or a worktree named one.
    checkout, branch = checkout_and_branch(resolved)
    if not checkout:
        return
    if checkout != repo and not checkout.startswith(repo + os.sep):
        return

    # HEAD and the branch are read in the worktree, since that is where the
    # commit landed; only the marker goes to the main checkout, because a
    # worktree is deleted when its branch merges and an obligation recorded
    # inside one dies with it.
    touched = {p for p in committed_paths(resolved) if is_config_asset(p)}
    if not touched:
        return

    # Scoped by branch: the obligation is an audit for what *this* branch
    # changed. Unscoped, switching branches carries the warning across and the
    # obvious fix -- clearing it -- discards the other branch's obligation.
    # The format is duplicated in scripts/audit_assets.py rather than imported,
    # because a hook must run under whatever interpreter settings.json names
    # and cannot depend on this repo's layout.
    marker = os.path.join(repo, MARKER)
    try:
        with open(marker) as fh:
            lines = {line.rstrip("\n") for line in fh if line.strip()}
    except OSError:
        lines = set()
    except ValueError:
        # Text mode, so a stray non-UTF-8 byte anywhere in the file raises
        # UnicodeDecodeError -- a ValueError, not the OSError above. Treating
        # the marker as empty is safe now that the write only appends: the
        # existing entries stay on disk regardless of whether they were read.
        lines = set()

    mine = {f"{branch}\t{asset}" for asset in touched}
    if mine <= lines:
        # Already owed for these assets on this branch. Asking again on every
        # later commit is the nagging this design exists to avoid.
        return

    # Appended, never rewritten. The read-modify-write this replaces lost
    # entries whenever two agents committed against one marker: each read the
    # set, added its own, and wrote the whole file back over the other's. With
    # eight at once it kept one entry in eight, and truncate-on-open meant a
    # kill at the hook's 10s timeout left the file empty or torn mid-line --
    # both observed. A single small O_APPEND write cannot interleave and
    # cannot truncate, which is prose-writing.py's O_CREAT|O_EXCL idiom again:
    # let the filesystem do the mutual exclusion rather than a read and a
    # hope. Both readers de-duplicate and sort at the point of display, so
    # nothing needed the file to be a sorted set on disk.
    body = "".join(f"{line}\n" for line in sorted(mine)).encode()
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, body)
        finally:
            os.close(fd)
    except OSError:
        # Cannot record it, so do not claim it was recorded.
        return

    lines |= mine

    # A set, not a list: a marker written before branch scoping existed holds
    # unscoped lines, and an asset present both ways was listed twice. Found in
    # production, by this hook reporting the same path to itself twice.
    owed = sorted(
        {
            line.partition("\t")[2] or line
            for line in lines
            if line.partition("\t")[0] == branch or "\t" not in line
        }
    )
    # Count and list come from the same set. Pairing len(all) with a list of
    # only the new ones read as "5 assets (scripts/x.py)" with no ellipsis.
    # json.dumps per path: these come from `git diff-tree` and land in agent
    # context, so they are content this repo did not author in the place an
    # instruction would be obeyed. Same framing rule as friction.py's excerpt.
    listed = ", ".join(json.dumps(asset) for asset in owed[:4])
    more = ", ..." if len(owed) > 4 else ""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"This branch has changed {len(owed)} claude-config "
                        f"asset(s) ({listed}{more}). Before integrating, run "
                        "`pixi run audit` and invoke the config-audit skill "
                        "once -- not once per commit, then "
                        "`pixi run audit --clear-owed`."
                    ),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
