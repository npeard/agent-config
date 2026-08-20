#!/usr/bin/env python
"""Report assertion bounds that a diff loosened.

The house rule is to delete a flaky gate rather than edge its threshold up
until it passes, because a gate edited to keep passing trains everyone to
ignore red. The edit is mechanically visible; whether it is a loosening or a
correction is not.

So this **reports and does not gate**. A bound can legitimately move -- a
wrong unit, a limit expressed the other way round -- and a check that is
routinely overridden teaches people to override it. Detection is mechanical,
the verdict stays with review. `--strict` is available for a caller that
wants to fail.

Usage:
    python scripts/thresholds.py [--base REF] [--strict]
    git diff ... | python scripts/thresholds.py --stdin
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

# Scientific notation matters: without it `abs=1e-9 -> abs=1e-3` parses as
# 9 -> 3 and reads as a tightening, silently missing a tolerance relaxed
# by six orders of magnitude.
# Underscores must sit *between* digits: `[\d_]*` matched the "1_" inside
# an identifier like `v1_norm`, and float("1_") raises, so any diff
# touching such an assertion aborted the whole run with a traceback.
NUMBER = re.compile(r"\d+(?:_\d+)*(?:\.\d+)?(?:[eE][+-]?\d+)?")
# Comparisons whose bound is relaxed by moving the literal in this direction.
LOOSER_WHEN_LARGER = ("<", "<=")
LOOSER_WHEN_SMALLER = (">", ">=")
# Tolerances are looser when larger, whatever the surrounding comparison.
TOLERANCE = re.compile(r"\b(?:abs|rel|delta|atol|rtol|tolerance)\s*=\s*")


def shape(line: str) -> str:
    """The line with every number replaced, so two versions can be matched."""
    return NUMBER.sub("#", line.strip())


def numbers(line: str) -> list[float]:
    return [float(m.group()) for m in NUMBER.finditer(line)]


def operator(line: str) -> str | None:
    for op in ("<=", ">=", "<", ">"):
        if op in line:
            return op
    return None


def loosened(before: str, after: str) -> str | None:
    """A description of the loosening, or None."""
    old, new = numbers(before), numbers(after)
    if len(old) != len(new) or old == new:
        return None
    changed = [(o, n) for o, n in zip(old, new, strict=True) if o != n]
    if not changed:
        return None
    o, n = changed[0]

    if TOLERANCE.search(after):
        return f"tolerance {o} -> {n}" if n > o else None
    op = operator(after)
    if op in LOOSER_WHEN_LARGER and n > o:
        return f"upper bound {o} -> {n}"
    if op in LOOSER_WHEN_SMALLER and n < o:
        return f"lower bound {o} -> {n}"
    return None


def hunks(diff: str):
    """Yield (path, removed_lines, added_lines) per hunk."""
    path, removed, added = None, [], []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            # Flush before switching files. Updating `path` first attributed
            # the previous file's hunk to the next file, sending a reviewer
            # somewhere the finding is not.
            if path and (removed or added):
                yield path, removed, added
                removed, added = [], []
            path = line[6:]
        elif line.startswith("@@"):
            if path and (removed or added):
                yield path, removed, added
            removed, added = [], []
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if path and (removed or added):
        yield path, removed, added


def findings(diff: str) -> list[str]:
    out = []
    for path, removed, added in hunks(diff):
        by_shape: dict[str, str] = {}
        for line in removed:
            if "assert" in line or TOLERANCE.search(line):
                by_shape.setdefault(shape(line), line)
        for line in added:
            if "assert" not in line and not TOLERANCE.search(line):
                continue
            before = by_shape.get(shape(line))
            if before is None:
                continue
            why = loosened(before, line)
            if why:
                out.append(
                    f"{path}: {why}\n      - {before.strip()}\n      + {line.strip()}"
                )
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="main", help="ref to diff against")
    parser.add_argument("--stdin", action="store_true", help="read a diff from stdin")
    parser.add_argument("--strict", action="store_true", help="exit 1 on a finding")
    args = parser.parse_args(argv)

    if args.stdin:
        diff = sys.stdin.read()
    else:
        try:
            diff = subprocess.run(
                ["git", "diff", f"{args.base}...HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Could not diff against {args.base}.")
            return 0

    found = findings(diff)
    if not found:
        print("No loosened assertion bounds.")
        return 0
    print("Loosened assertion bounds -- delete the gate rather than raising it,")
    print("or say in review why this is a correction and not a loosening:\n")
    for f in found:
        print(f"  {f}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
