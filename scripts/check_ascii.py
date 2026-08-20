#!/usr/bin/env python
"""Fail if any tracked source/doc file contains non-ASCII characters.

For projects that enforce an ASCII-only source convention (e.g. mathematical
notation in docstrings, comments, and strings written as plain text or LaTeX
-- "rho", "<psi|", "->" -- rather than Unicode glyphs). Ruff's RUF001/2/3 only
catch the *confusable* subset (homoglyphs); this check catches every
non-ASCII codepoint.

Usage:
    python scripts/check_ascii.py [FILE ...]

With no arguments, scans all git-tracked ``*.py`` and ``*.md`` files. With
arguments (as passed by pre-commit), scans exactly those files.

A file whose subject *is* Unicode punctuation cannot demonstrate it in ASCII,
so one file may opt out by carrying a marker in its first lines, in whatever
comment syntax it uses::

    # check-ascii: allow - reason
    <!-- check-ascii: allow - reason -->

The reason is required. A marker with nothing after it fails rather than
skipping: an exemption that need not say why is a silent hole, and the point
of the marker is that a future reader finds the rationale where the exemption
is. The declaration lives in the file it describes for the same reason
`# claude-hook:` does -- it cannot drift from what it applies to.

The marker is only honoured near the top of the file, so a passing mention
deep in prose cannot disable the check. That also keeps this script scannable
by itself: the literal text above sits below the window, which
tests/test_check_ascii.py pins.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCANNED_SUFFIXES = {".py", ".md"}
MARKER_SCAN_LINES = 10
# Three conditions, and each one closed a real hole. The marker must (a) open
# its line as a comment, (b) not be indented like a code block, and (c) not be
# inside a fence. Merely "contains the marker text somewhere in the first ten
# lines" let any document that *described* the convention exempt itself
# entirely -- and anchoring alone was not enough, because a fenced or indented
# example of the marker is the natural way to document it. A file explaining
# how to opt out is the last file that should be silently opted out.
MARKER = re.compile(
    r"^(?: {0,3})(?:#|<!--|//|%|;)\s*check-ascii:\s*allow\b(?P<rest>.*)",
)
FENCE = re.compile(r"^\s*(?:```|~~~)")


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py", "*.md"], capture_output=True, text=True, check=True
    )
    return out.stdout.split()


def has_reason(rest: str) -> bool:
    """Whether the text after the marker explains anything.

    Deliberately duplicated from scripts/suppressions.py rather than imported:
    each script here is meant to be copied into another repo on its own, and a
    cross-import would break the one property that makes them portable.
    """
    return bool(re.search(r"[A-Za-z]{3}", rest.strip(" -#:<>!")))


def read_lines(path: Path) -> list[str]:
    """The file's lines, with their terminators kept.

    One read serves both the marker scan and the character scan. Reading twice
    let the two disagree: the marker scan tolerated a decode error while the
    character scan did not, so an unreadable or non-UTF-8 file came out of a
    pre-commit run as a traceback rather than as a violation line.

    `keepends` is not cosmetic. `str.splitlines()` also breaks on U+2028,
    U+2029 and U+0085, so dropping the terminators consumed those three as
    line breaks and they never reached the character scan -- an ASCII gate
    blind to three non-ASCII codepoints, which is exactly the class of
    invisible character that survives a paste from a PDF. Verified before and
    after.
    """
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def marker_remainder(lines: list[str]) -> str | None:
    """The raw text following a real marker near the top, else None.

    Returns the remainder even when it is empty, so the caller can tell "no
    marker" (skip nothing) from "marker with no reason" (a violation).

    Lines inside a fenced code block are skipped, because an example of the
    marker is not an instance of it. Without that, the file most likely to
    show the marker -- the one documenting it -- was the file most likely to
    disable the check on itself.
    """
    in_fence = False
    for line in lines[:MARKER_SCAN_LINES]:
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = MARKER.match(line)
        if match:
            return match.group("rest")
    return None


def scan(path: Path) -> list[str]:
    """Every violation in one file."""
    try:
        lines = read_lines(path)
    except UnicodeDecodeError:
        # Reporting beats skipping: a file that will not decode as UTF-8
        # certainly is not ASCII either.
        return [f"{path}: not valid UTF-8, so it cannot be ASCII either"]
    except OSError as exc:
        # Kept distinct from the decode case. Reported as an encoding problem,
        # a permission or I/O failure sends the reader hunting for bad bytes
        # in a file that has none.
        return [f"{path}: cannot be read ({exc.strerror or exc})"]
    rest = marker_remainder(lines)
    if rest is not None:
        if has_reason(rest):
            return []
        return [
            (
                f"{path}: 'check-ascii: allow' with no reason -- say why, or "
                "remove the marker"
            )
        ]
    return [
        f"{path}:{lineno}:{col}: non-ASCII {ch!r} (U+{ord(ch):04X})"
        for lineno, line in enumerate(lines, start=1)
        for col, ch in enumerate(line, start=1)
        if ord(ch) > 127
    ]


def main(argv: list[str]) -> int:
    files = argv or tracked_files()
    violations: list[str] = []
    for f in files:
        path = Path(f)
        if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
            continue
        violations.extend(scan(path))
    if violations:
        print("ASCII check failed (use plain text or LaTeX instead):")
        for v in violations:
            print(f"  {v}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
