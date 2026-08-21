#!/usr/bin/env python
"""Require every linter suppression to carry a reason.

A suppression stops the linter checking that line forever, so the rule is
that it must say why. Requiring a reason on *every* one is a ratchet that
needs no stored baseline: a new bare suppression fails immediately, and a
justified one is a deliberate act with its rationale attached where a future
reader will look.

What it cannot do is judge whether a reason is any good. That stays a review
question, which is why the house rule survives alongside this check rather
than being replaced by it.

Usage:
    python scripts/suppressions.py [FILE ...]

With no arguments, scans all git-tracked ``*.py`` files. With arguments, as
passed by pre-commit, scans exactly those.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# These two contain suppression markers as *data* -- the patterns below and
# the fixtures that exercise them -- so scanning them would report the
# checker for describing what it checks. Pinned by a test so the list cannot
# quietly grow into a way of hiding real suppressions.
SELF_EXEMPT = frozenset({"scripts/suppressions.py", "tests/test_suppressions.py"})

# Each pattern captures whatever follows the marker and its codes; if that
# remainder still holds words once punctuation is stripped, it is a reason.
PATTERNS = (
    ("noqa", re.compile(r"#\s*noqa(?::[\sA-Z0-9,]*)?(?P<rest>.*)$")),
    ("type: ignore", re.compile(r"#\s*type:\s*ignore(?:\[[^\]]*\])?(?P<rest>.*)$")),
    ("pragma: no cover", re.compile(r"#\s*pragma:\s*no\s+cover(?P<rest>.*)$")),
    ("nosec", re.compile(r"#\s*nosec(?::?[\sA-Z0-9,]*)?(?P<rest>.*)$")),
)


def tracked_python_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return out.stdout.split()


def has_reason(rest: str) -> bool:
    """Whether the text after a marker's codes explains anything."""
    return bool(re.search(r"[A-Za-z]{3}", rest.strip(" -#:")))


def scan(path: Path) -> tuple[int, list[str]]:
    """(justified count, complaints) for one file."""
    justified, complaints = 0, []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return 0, []
    for lineno, line in enumerate(lines, start=1):
        for name, pattern in PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            if has_reason(match.group("rest")):
                justified += 1
            else:
                complaints.append(
                    f"{path}:{lineno}: '{name}' with no reason -- say why, "
                    "or fix the cause"
                )
            break
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
    targets = argv or tracked_python_files()
    justified, complaints = 0, []
    for name in targets:
        if name in SELF_EXEMPT:
            continue
        path = Path(name)
        if path.suffix != ".py" or not path.is_file():
            continue
        count, found = scan(path)
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
