#!/usr/bin/env python
"""Require every linter suppression to carry a reason.

A suppression stops the linter checking that line forever, so the rule is
that it must say why. Requiring a reason on *every* one is a ratchet that
needs no stored baseline: a new bare suppression fails immediately, and a
justified one is a deliberate act with its rationale attached where a future
reader will look.

Three channels, because a rule can be silenced at three widths: a marker on
one line, a directive covering a whole file, and a key in the linter's own
config covering the entire project. The last is the cheapest of them -- one
line, no source file touched -- so watching only the first left the check
guarding the door that was hardest to walk through.

This file and its test are scanned like any other, with no self-exemption.
They once had one, on the theory that a checker must quote the markers it
looks for -- but neither file actually tripped the check, so the exemption
protected nothing while standing as a blanket file-level pass over the two
files nobody would think to audit. Both keep their example markers assembled
from pieces at runtime instead, which costs a line and closes the hole.

What it cannot do is judge whether a reason is any good, or whether the width
claimed is the width needed. That stays a review question, which is why the
house rule survives alongside this check rather than being replaced by it.

Usage:
    python scripts/suppressions.py [FILE ...]

With no arguments, scans every git-tracked ``*.py`` file and every tracked
linter config file (see CONFIG_FILENAMES). With arguments, as passed by
pre-commit, scans exactly those.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Each pattern matches a marker and the codes it names, and nothing more:
# what follows on the line is the candidate reason, and `markers` decides
# where it ends.
#
# The file-level directives come first in the tuple only for reading order.
# They matter because they are strictly broader than the line markers -- one
# of them switches a rule off for every line of the file -- and they were
# the hole here: the line-level noqa pattern requires the marker to follow
# its `#` directly, so a leading `ruff:` or `flake8:` matched nothing at
# all, and disabling the linter for a whole file was free.
#
# Of the mypy directives only the two that *loosen* checking are listed. The
# rest of that namespace tightens it (`mypy: strict`) or is unrelated, and a
# check that complained about a file asking for stricter typing would teach
# people to stop reading its output.
PATTERNS = (
    ("ruff: noqa", re.compile(r"#\s*ruff:\s*noqa(?::[\sA-Z0-9,]*)?")),
    ("flake8: noqa", re.compile(r"#\s*flake8:\s*noqa(?::[\sA-Z0-9,]*)?")),
    ("mypy: ignore-errors", re.compile(r"#\s*mypy:\s*ignore-errors")),
    # The quoted alternative comes first so a value holding a comma and a
    # space is consumed whole; the bare form would stop at that space and
    # read the remaining codes as a reason.
    (
        "mypy: disable-error-code",
        re.compile(r"#\s*mypy:\s*disable-error-code(?:\s*=\s*(?:\"[^\"]*\"|[\w,-]*))?"),
    ),
    ("noqa", re.compile(r"#\s*noqa(?::[\sA-Z0-9,]*)?")),
    ("type: ignore", re.compile(r"#\s*type:\s*ignore(?:\[[^\]]*\])?")),
    ("pragma: no cover", re.compile(r"#\s*pragma:\s*no\s+cover")),
    ("nosec", re.compile(r"#\s*nosec(?::?[\sA-Z0-9,]*)?")),
)


def tracked_files() -> list[str] | None:
    """Every tracked file, or None if git could not be asked.

    Returning [] here was a false green: outside a repository, or with git
    missing, the check printed "0 unjustified" having read nothing. Kept in
    the same shape as scripts/check_ascii.py's copy, which failed the other
    way and tracebacked.

    Unfiltered, because `main` already decides what it can read. A `*.py`
    pathspec here was a second definition of that set, and the two disagreed
    -- it made the config-file scan below unreachable on the fallback path.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    # NUL-separated, because without -z git quotes any path holding a
    # space or a non-ASCII byte, and the quoted form matches no file on
    # disk -- so main's is_file() filter dropped it without a word.
    return [f for f in out.stdout.split("\0") if f]


NO_GIT = (
    "Cannot list tracked files: not inside a git repository, or git is not "
    "installed. Pass the files to scan as arguments."
)


def has_reason(rest: str) -> bool:
    """Whether the text after a marker's codes explains anything."""
    return bool(re.search(r"[A-Za-z]{3}", rest.strip(" -#:")))


def markers(line: str) -> list[tuple[str, str]]:
    """Every marker on one line, each with the text that could justify it.

    Both properties here cost a hole to learn. *Every* marker, because
    stopping at the first pattern that matched left a second marker on the
    line unexamined. And a candidate reason ends where the next marker
    begins, because running it to end-of-line let a documented marker
    justify a bare one beside it -- a bare type-ignore followed by a
    reasoned noqa scored as fully justified, borrowing the reason that
    belonged to the noqa. TestEveryMarkerOnTheLine holds the literal case;
    it cannot be written here, since this file is scanned like any other.
    """
    found = sorted(
        (m.start(), m.end(), name)
        for name, pattern in PATTERNS
        for m in pattern.finditer(line)
    )
    # Each marker's reason runs to the next marker's start, the last one's to
    # the end of the line.
    return [
        (name, line[end : found[i + 1][0] if i + 1 < len(found) else len(line)])
        for i, (_, end, name) in enumerate(found)
    ]


def read_lines(path: Path) -> tuple[list[str], list[str]]:
    """(lines, complaints), where a complaint means the file would not open.

    Skipping an unreadable file quietly is the same false green as an
    enumeration that failed: nothing was checked and the run still passed.
    scripts/check_ascii.py already reports this case, and the two had settled
    it differently for no recorded reason. `errors="replace"` keeps a decode
    problem out of it -- an ASCII gate is what should complain about bytes.
    """
    try:
        return path.read_text(errors="replace").splitlines(), []
    except OSError as exc:
        return [], [
            (
                f"{path}: cannot be read ({exc.strerror or exc}), so it cannot "
                "be shown to be free of suppressions"
            )
        ]


def scan(path: Path) -> tuple[int, list[str]]:
    """(justified count, complaints) for one file."""
    justified = 0
    lines, complaints = read_lines(path)
    for lineno, line in enumerate(lines, start=1):
        for name, rest in markers(line):
            if has_reason(rest):
                justified += 1
            else:
                complaints.append(
                    f"{path}:{lineno}: '{name}' with no reason -- say why, "
                    "or fix the cause"
                )
    return justified, complaints


# Linter configuration files, named rather than matched by suffix. A data
# TOML with an `ignore` key of its own is not a linter config, and scanning
# every .toml would make this check noise. The INI-syntax members are in the
# same list because the scan is line-based: `key = value` with `#` comments
# reads the same in both.
CONFIG_FILENAMES = frozenset(
    {
        "pyproject.toml",
        "ruff.toml",
        ".ruff.toml",
        "setup.cfg",
        "tox.ini",
        ".flake8",
        "mypy.ini",
        ".mypy.ini",
    }
)

# Keys that switch a rule off for everything the linter sees. Compared on the
# last dotted segment, so ruff's `lint.ignore = [...]` form is caught too.
#
# Path exclusions (`exclude`, `extend-exclude`) are deliberately absent.
# "These files are not ours to lint" is a different claim from "this rule
# does not apply to our code", and demanding a rationale for excluding a
# build directory is the sort of noise that gets a check ignored wholesale.
# The match is on the key name alone, not on which tool owns the table, so a
# tool whose path list happens to be spelled `ignore` (pyright's is) will be
# asked for a reason it arguably does not owe. Reading the table path to
# decide would mean tracking every tool's schema here; one comment is the
# cheaper answer, and the reason it wants is one line.
CONFIG_KEYS = frozenset(
    {
        "ignore",
        "extend-ignore",
        "per-file-ignores",
        "extend-per-file-ignores",
        "disable_error_code",
        "ignore_errors",
    }
)

# Every assignment inside this table is a suppression whatever its key, since
# the keys there are file globs. Matching key names alone would have left the
# entire table unwatched.
PER_FILE_TABLE = re.compile(r"^\[.*per-file-ignores.*\]")
# The quoted alternatives are not decoration: a per-file-ignores key is a
# path glob, and a path may contain a space, which an unbroken run of
# non-space characters could not span.
ASSIGNMENT = re.compile(r"""^(?P<key>"[^"]*"|'[^']*'|[^\s=#;]+)\s*=""")
COMMENT = re.compile(r"[#;](?P<text>.*)")


def array_end(lines: list[str], start: int) -> int:
    """Index of the line closing a value that opens a multi-line array.

    `start` itself when the value is complete on one line. The reason for a
    multi-entry ignore list is usually written *inside* the brackets, one
    comment per code, so a scan that looked only at the assignment line would
    report the best-documented form of all as unjustified.
    """
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("[") - lines[i].count("]")
        if depth <= 0:
            return i
    return len(lines) - 1


def config_scan(path: Path) -> tuple[int, list[str]]:
    """(justified count, complaints) for one linter config file.

    A reason may sit on the assignment line, inside a multi-line array, or in
    the contiguous comment block directly above -- all three are where a
    reader would look, and insisting on one of them would only teach people
    to fight the checker.
    """
    justified = 0
    lines, complaints = read_lines(path)
    in_per_file_table = False
    preceding: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith(("#", ";")):
            preceding.append(stripped)
            i += 1
            continue
        if stripped.startswith("["):
            in_per_file_table = bool(PER_FILE_TABLE.match(stripped))
        elif (match := ASSIGNMENT.match(stripped)) and (
            in_per_file_table or match.group("key").rsplit(".", 1)[-1] in CONFIG_KEYS
        ):
            end = array_end(lines, i)
            reason = " ".join(
                preceding
                + [
                    m.group("text")
                    for m in map(COMMENT.search, lines[i : end + 1])
                    if m
                ]
            )
            if has_reason(reason):
                justified += 1
            else:
                complaints.append(
                    f"{path}:{i + 1}: '{match.group('key')}' silences a rule "
                    "for the whole project with no reason -- say why, or fix "
                    "the cause"
                )
            i = end
        preceding = []
        i += 1
    return justified, complaints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "paths",
        nargs="*",
        help="files to scan; pre-commit passes the staged set, "
        "and an empty list falls back to every tracked file",
    )
    argv = parser.parse_args(argv).paths
    targets = argv or tracked_files()
    if targets is None:
        print(NO_GIT, file=sys.stderr)
        return 1
    justified, complaints = 0, []
    for name in targets:
        path = Path(name)
        if not path.is_file():
            continue
        if path.name in CONFIG_FILENAMES:
            count, found = config_scan(path)
        elif path.suffix == ".py":
            count, found = scan(path)
        else:
            continue
        justified += count
        complaints.extend(found)

    if complaints:
        print("Suppressions without a reason:")
        for c in complaints:
            print(f"  {c}")
        print(f"\n{len(complaints)} unjustified, {justified} justified")
        return 1

    # Report the total even on success: no suppressions and eleven justified
    # suppressions are different states, and only one of them is worth
    # feeling good about.
    print(f"Suppressions: {justified} justified, 0 unjustified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
