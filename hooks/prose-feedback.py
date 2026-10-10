#!/usr/bin/env python3
# claude-hook: PostToolUse Write|Edit|Bash
"""Hand the agent the measurable half of a prose edit as it happens.

Fires after a Write, Edit, apply_patch or Bash call that changed a .tex or
.typ file, and reports forward references (scripts/check_forward_refs.py, on
the document that includes the file) and sentence shape
(scripts/prose_metrics.py, on the file itself, since it does not follow
\\input). A number after each edit, against the session's first, changes
sentence length where style advice did not.

A forward reference in a file the tool named blocks; one elsewhere in the
document, or in a file only observed through Bash, is only listed. A block
over a chapter the agent never touched is one it cannot clear, and a gate
that cannot be cleared is trained away.

A block is `{"decision": "block", "reason": ...}` and nothing else: the
reason alone reaches the agent (verified by hand on Claude Code 2.1.296), so
the same text in additionalContext would arrive twice. Anything else is
information and goes in additionalContext only.

Never blocks on failure: a script that crashes, times out or prints something
unparsable yields no feedback and exit 0, because a broken feedback hook must
not stop edits. Everything runs concurrently to fit the hook's 10 s; see
TIMEOUT_SECONDS.

Stdlib only: the interpreter that runs a hook is named in
~/.claude/settings.json, outside this repo and its checks.
"""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def resolve(path: str) -> str:
    """Resolved and forward-slashed, with real case preserved.

    Use this whenever the result will touch the filesystem.
    """
    return os.path.realpath(os.path.normpath(path)).replace(os.sep, "/")


def canonical(path: str) -> str:
    """Resolved and lowercased: the form every pattern test uses."""
    return resolve(path).lower()


# Same resolution order as audit-owed.py: the env overrides, then the link the
# installer writes, so the hook works from any clone path.
MASTER_REPO = canonical(
    os.path.expanduser(
        os.environ.get("AGENT_CONFIG_REPO")
        or os.environ.get("CLAUDE_CONFIG_REPO")
        or "~/.agents/agent-config"
    )
)
SUFFIXES = (".tex", ".typ")

# Generated output, dependencies, agent configuration, and session-scoped
# scaffolding. `build/` matters most for these projects: a Snakemake pipeline
# writes .tex into it, and advising a rewrite of a generated file is worse
# than useless. The rest are kept in step with prose-writing.py's list, so
# the two hooks agree on what counts as a draft. prose-writing.py's stem
# screen is not copied: every stem on it (readme, todo, ...) names a Markdown
# or text file, never a .tex or .typ.
EXCLUDED_PATHS = (
    # One level, not two: `*/skills/*/*` let a file directly in skills/ through.
    "*/skills/*",
    "*/.claude/*",
    "*/.codex/*",
    "*/memory/*",
    "*/docs/superpowers/*",
    "*/scratch/*",
    # This harness directs agents to write throwaway files to a scratchpad
    # path, and measuring a file nobody will read is noise.
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

# Codex's apply_patch carries the patch text where Bash carries a command, and
# names each file it writes in a header line. "Move to" is the file that
# exists afterwards when an update renames.
PATCH_FILE = re.compile(
    r"^\*\*\* (?:Add File|Update File|Move to): (.+)$", re.MULTILINE
)


def relevant(path: str) -> bool:
    if not path.endswith(SUFFIXES):
        return False
    # The trailing slash matters: a bare prefix test would also swallow a
    # sibling directory like "agent-config-other".
    if path.startswith(MASTER_REPO + "/"):
        return False
    # Asked of the platform rather than pattern-matched, because the temp
    # directory is /tmp, /private/tmp or /var/folders/... depending on the
    # machine, and prose written there is by definition throwaway.
    if path.startswith(canonical(tempfile.gettempdir()) + "/"):
        return False
    # fnmatchcase, not fnmatch: `path` is already lowercased, so fnmatch's
    # platform-dependent normcase would be a second, invisible normalization.
    return not any(fnmatch.fnmatchcase(path, p) for p in EXCLUDED_PATHS)


SCRIPTS = Path(os.path.realpath(__file__)).resolve().parent.parent / "scripts"
# Both registrars give a hook 10 s. Every script runs concurrently, so the git
# listing plus one script's timeout is the whole budget, with room left for
# the hook's own start-up.
GIT_TIMEOUT_SECONDS = 2
TIMEOUT_SECONDS = 6
MAX_FILES = 2
FIRST_CALL_WINDOW_SECONDS = 10
MAX_WALK_DEPTH = 3
MAX_WALK_FILES = 200
MAX_LINES = 15
MAX_VIOLATIONS = 10
MAX_LONGEST = 3
EXCERPT_CHARS = 120


def run_json(script: str, args: list[str], ok_codes: tuple[int, ...]):
    """The script's --json output, or None on any failure."""
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--json", *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode not in ok_codes:
            return None
        return json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def session_file(session, key: str, suffix: str) -> Path:
    digest = hashlib.sha256(f"{session}\0{key}".encode()).hexdigest()[:16]
    return stamp_dir() / f"{digest}{suffix}"


def baseline(session, key: str, current):
    """The session's first measurement under `key`; records `current` if none."""
    if not session:
        return None
    stamp = session_file(session, key, ".json")
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        return json.loads(stamp.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return None
    try:
        stamp.write_text(json.dumps(current), encoding="utf-8")
    except OSError:
        pass
    return None


def signed(value: float, digits: int) -> str:
    return f"{value:+.{digits}f}"


def metrics_line(sentences: dict, first) -> str:
    count, median, p90 = (
        sentences["count"],
        sentences["median_words"],
        sentences["p90_words"],
    )
    chained = round(100 * sentences["chained_clause_rate"])
    line = (
        f"Prose: {count} sentences, median {median:g} words, p90 {p90:g}, "
        f"{chained}% chained-clause"
    )
    if first is None:
        return line
    line += (
        f" (since first this session: sentences {signed(count - first['count'], 0)}, "
        f"median {signed(median - first['median_words'], 1)}, "
        f"p90 {signed(p90 - first['p90_words'], 0)}, "
        f"chained {signed(chained - round(100 * first['chained_clause_rate']), 0)} pp)"
    )
    # Said in words because a bare "+5" was measured not to work: agents
    # shown only the delta kept splitting sentences. Conditional, because a
    # rise is right when the edit was asked to add content.
    if count > first["count"]:
        line += (
            "; if this edit revises existing prose, cut sentences rather than "
            "split them"
        )
    return line


HERE_HEADER = (
    "Forward references (a reader meets the reference before its "
    "definition; reorder or restate, then re-check):"
)
ELSEWHERE_HEADER = "Forward references elsewhere in this document:"


# A Bash write's paths come from `git ls-files`, so a file name is content the
# repo may not have authored. Path-shaped names print bare; anything else is
# framed as a JSON string, like labels and excerpts.
PLAIN_PATH = re.compile(r"[\w./-]+")


def shown_path(path: str) -> str:
    return path if PLAIN_PATH.fullmatch(path) else json.dumps(path)


def violation_lines(header: str, violations: list, root: str, room: int) -> list[str]:
    """At most `room` lines: the header, what fits, then a "(+N more)" line."""
    if not violations or room < 2:
        return []
    here = os.path.dirname(root)

    def name(path: str) -> str:
        return shown_path(os.path.relpath(path, here))

    shown = min(len(violations), MAX_VIOLATIONS)
    if shown < len(violations) or shown + 1 > room:
        shown = min(shown, room - 2)
        if shown < 1:
            return []
    lines = [header]
    for item in violations[:shown]:
        # json.dumps: the label is file content, framed as data, not prose.
        lines.append(
            f"  {name(item['file'])}:{item['line']} {item['ref']} "
            f"label {json.dumps(item['label'])} defined at "
            f"{name(item['defined_file'])}:{item['defined_line']}"
        )
    if len(violations) > shown:
        lines.append(f"  (+{len(violations) - shown} more)")
    return lines


def long_lines(sentences: dict, room: int) -> list[str]:
    # The script's own threshold, so the hook cannot disagree with it.
    threshold = sentences["long_threshold_words"]
    over = [s for s in sentences["longest"] if s["words"] > threshold]
    over.sort(key=lambda s: -s["words"])
    out = []
    for item in over[: min(MAX_LONGEST, max(room, 0))]:
        text = " ".join(item["text"].split())
        if len(text) > EXCERPT_CHARS:
            text = text[: EXCERPT_CHARS - 3] + "..."
        out.append(f"  line {item['line']} ({item['words']} words): {json.dumps(text)}")
    return out


def measure(path: str):
    """(root, violations, sentences) for one file; any may be empty or None."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending_forward = pool.submit(
            run_json, "check_forward_refs.py", ["--containing", path], (0, 1)
        )
        pending_metrics = pool.submit(run_json, "prose_metrics.py", [path], (0,))
        forward, metrics = pending_forward.result() or {}, pending_metrics.result()
    return (
        str(forward.get("root") or path),
        forward.get("violations") or [],
        (metrics or {}).get("sentences"),
    )


def file_lines(path, measured, session, share, elsewhere):
    """The file's report within `share` lines, and whether it has a reference
    in the file itself. `elsewhere` is empty when another file already listed
    this document's other references.
    """
    root, violations, sentences = measured
    here = [v for v in violations if canonical(v["file"]) == canonical(path)]
    # One line is kept for the metrics.
    lines = violation_lines(HERE_HEADER, here, root, share - 1)
    lines += violation_lines(ELSEWHERE_HEADER, elsewhere, root, share - 1 - len(lines))
    if sentences:
        lines.append(metrics_line(sentences, baseline(session, path, sentences)))
        lines += long_lines(sentences, share - len(lines))
    return lines, bool(here)


def stamp_dir() -> Path:
    """Where the per-session baselines and call stamps live, per user.

    On POSIX the temp directory is shared, so an unnamespaced directory
    created by another user is not writable by this one.
    """
    getuid = getattr(os, "getuid", None)
    suffix = f"-{getuid()}" if getuid else ""
    return Path(tempfile.gettempdir()) / f"claude-prose-feedback{suffix}"


def previous_call(session) -> float:
    """When this session's hook last ran; the stamp is then moved to now.

    Moved on every call, whatever the call goes on to do, so a Bash call is
    credited only with what changed since the session's previous tool call.
    """
    since = time.time() - FIRST_CALL_WINDOW_SECONDS
    # Without a session there is nothing to key a stamp on, and the string
    # "None" would share one across unrelated sessions.
    if not session:
        return since
    stamp = session_file(session, "", ".stamp")
    try:
        since = stamp.stat().st_mtime
    except OSError:
        pass
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except OSError:
        pass
    return since


def walked(cwd: str) -> list[str]:
    """The .tex and .typ files of a bounded walk, standing in for git."""
    found, seen = [], 0
    for directory, subdirs, files in os.walk(cwd):
        if os.path.relpath(directory, cwd).count(os.sep) >= MAX_WALK_DEPTH:
            subdirs.clear()
        found += [os.path.join(directory, f) for f in files if f.endswith(SUFFIXES)]
        seen += len(files)
        if seen >= MAX_WALK_FILES:
            break
    return found


def changed_files(cwd: str, since: float) -> list[str]:
    """.tex and .typ files under `cwd` changed after `since`, newest first.

    Observed, not read off the command text: a program in a heredoc writes
    files no shell parse can see, and a misread `cd` measures the wrong file.
    """
    try:
        listed = subprocess.run(
            ["git", "-C", cwd, "ls-files", "-z", "-m", "-o", "--exclude-standard"]
            + ["--", "*.tex", "*.typ"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        ).stdout
        paths = {os.path.join(cwd, name) for name in listed.split("\0") if name}
    except (OSError, subprocess.SubprocessError):
        paths = set(walked(cwd))
    stamped = []
    for path in paths:
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if mtime > since:
            stamped.append((mtime, path))
    return [path for _, path in sorted(stamped, reverse=True)]


def edited_paths(data: dict, tool_input: dict, since: float) -> tuple[list[str], bool]:
    """(paths, named): whether the tool itself named the paths.

    Only named paths may block. A checkout, stash pop or formatter run gives
    files fresh mtimes the agent did not edit, and a block it cannot attribute
    is a gate it cannot clear.
    """
    file_path = tool_input.get("file_path")
    command = tool_input.get("command")
    cwd = data.get("cwd")
    if isinstance(file_path, str) and file_path:
        return [file_path], True
    if not (isinstance(command, str) and isinstance(cwd, str) and cwd):
        return [], False
    # Keyed on the tool, not on the text: a Bash heredoc can carry a
    # "*** Update File:" line as data, and it names nothing written.
    if data.get("tool_name") == "apply_patch":
        return [
            os.path.join(cwd, os.path.expanduser(name.strip()))
            for name in PATCH_FILE.findall(command)
        ], True
    return changed_files(cwd, since), False


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(data, dict):
        return
    session = data.get("session_id")
    since = previous_call(session)
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    candidates, named = edited_paths(data, tool_input, since)
    paths = [
        path
        for path in map(resolve, candidates)
        if relevant(path.lower()) and os.path.isfile(path)
    ][:MAX_FILES]
    if not paths:
        return
    # Each file gets its share of the line budget, less a line naming it.
    share = MAX_LINES // len(paths) - (len(paths) > 1)
    try:
        with ThreadPoolExecutor(max_workers=len(paths)) as pool:
            measured = list(pool.map(measure, paths))
    except Exception:  # noqa: BLE001 -- a feedback hook must never stop an edit
        return
    reported = {canonical(p) for p in paths}
    listed, chunks, blocking = set(), [], False
    for path, item in zip(paths, measured):
        root = item[0]
        # Violations in files reported on their own are not "elsewhere".
        elsewhere = []
        if root not in listed:
            listed.add(root)
            elsewhere = [v for v in item[1] if canonical(v["file"]) not in reported]
        lines, has_here = file_lines(path, item, session, share, elsewhere)
        blocking = blocking or (named and has_here)
        if lines:
            prefix = (
                [f"{shown_path(os.path.basename(path))}:"] if len(paths) > 1 else []
            )
            chunks += prefix + lines
    if not chunks:
        return
    message = "\n".join(chunks)
    if blocking:
        output = {"decision": "block", "reason": message}
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": message,
            }
        }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
