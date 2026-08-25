#!/usr/bin/env python
"""Report bounds that a diff loosened -- in an assertion or in a named limit.

Named limits count because a ceiling held in `SOME_MAX = 1250` is the same
gate as `assert n <= 1250`, and raising it is the same edit.

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
# The lookaround keeps a digit that is part of a *name* from being read as a
# bound at all: `\d+` matched the "1" in `v1_norm`, so renaming `v1_norm` to
# `v2_norm` shaped identically and was reported as 1 -> 2. A detector that
# cries wolf on a rename is a detector that gets overridden.
NUMBER = re.compile(r"(?<![\w.])\d+(?:_\d+)*(?:\.\d+)?(?:[eE][+-]?\d+)?(?!\w)")
# Tolerances are looser when larger, whatever the surrounding comparison.
TOLERANCE = re.compile(r"\b(?:abs|rel|delta|atol|rtol|tolerance)\s*=\s*")

# An inline comment is stripped before anything else. `shape()` hashed the
# whole line, so `assert err < 0.5  # loosened` and `assert err < 0.001` had
# different shapes and never paired -- the one case where the loosening
# announces itself in words was the one case that went unreported. A `#`
# inside a string literal is truncated too; the remainder still yields the
# same bounds, because a bound is a number next to an operator.
COMMENT = re.compile(r"(?:#|//).*$")

# Read per comparison, not per line: `operator()` returned the first operator
# anywhere in the line, so `assert n > 100 and tol < 1e-6` relaxed to `n > 10`
# was judged against "<" and read as a tightening.
UPPER, LOWER, TOL = "upper bound", "lower bound", "tolerance"
# `x < 5` -- the literal is the ceiling.
BOUND = re.compile(rf"(?P<op><=|>=|<|>)\s*(?P<num>{NUMBER.pattern})")
# `5 < x` -- the same comparison written round the other way, so the literal
# is the floor. Both forms appear in real assertions and only one was handled.
REVERSED_BOUND = re.compile(rf"(?P<num>{NUMBER.pattern})\s*(?P<op><=|>=|<|>)")
TOLERANCE_BOUND = re.compile(rf"{TOLERANCE.pattern}(?P<num>{NUMBER.pattern})")

# A ceiling held in a named constant is the same gate as an assertion, and
# loosening it is the same edit -- but pairing required the substring
# "assert", so moving this repo's context ceilings out of
# tests/test_context_budget.py and into scripts/audit_assets.py made every one
# of them invisible here. Uppercase only: a lowercase local is a counter or an
# accumulator, and treating those as policy would report every increment.
NAMED_LIMIT = re.compile(
    rf"\b(?P<name>[A-Z][A-Z0-9_]*)\s*=\s*(?P<num>{NUMBER.pattern})"
)
# Direction has to be readable from the name, so only names that state one
# count. `THRESHOLD` deliberately does not: `OVERLAP_THRESHOLD` loosens upward
# while a `COVERAGE_THRESHOLD` loosens downward, and guessing would report
# half of all tightenings as loosenings.
CEILING_WORDS = ("MAX", "LIMIT", "CEILING", "BUDGET")
FLOOR_WORDS = ("MIN", "FLOOR")


def code(line: str) -> str:
    """The line without its inline comment or surrounding whitespace."""
    return COMMENT.sub("", line).strip()


def shape(line: str) -> str:
    """The line with every number replaced, so two versions can be matched."""
    return NUMBER.sub("#", code(line))


def numbers(line: str) -> list[float]:
    return [float(m.group()) for m in NUMBER.finditer(code(line))]


def bounds(line: str) -> list[tuple[str, float]]:
    """Every (kind, literal) bound the line states, in source order.

    Only lines that assert, set a tolerance, or name a limit are read: every
    `<` in a codebase is not a gate, and reporting loop conditions would bury
    the findings that matter.
    """
    text = code(line)
    if not ("assert" in text or TOLERANCE.search(text) or NAMED_LIMIT.search(text)):
        return []
    found: dict[tuple[int, int], tuple[str, float]] = {}
    for match in TOLERANCE_BOUND.finditer(text):
        found[match.span("num")] = (TOL, float(match.group("num")))
    for match in BOUND.finditer(text):
        kind = UPPER if match.group("op").startswith("<") else LOWER
        found.setdefault(match.span("num"), (kind, float(match.group("num"))))
    for match in REVERSED_BOUND.finditer(text):
        # Reversed reading of a literal already claimed above would double
        # count the middle of a chained `a <= 5 <= b` with opposite kinds.
        kind = LOWER if match.group("op").startswith("<") else UPPER
        found.setdefault(match.span("num"), (kind, float(match.group("num"))))
    for match in NAMED_LIMIT.finditer(text):
        name = match.group("name")
        if any(w in name for w in FLOOR_WORDS):
            kind = LOWER
        elif any(w in name for w in CEILING_WORDS):
            kind = UPPER
        else:
            continue
        found.setdefault(match.span("num"), (kind, float(match.group("num"))))
    return [found[span] for span in sorted(found)]


def loosened(before: str, after: str) -> str | None:
    """A description of the loosening, or None.

    Bounds are compared position by position. A line whose bound *count* or
    *kinds* changed is not reported: the comparison was restructured, and
    guessing which literal replaced which would invent a direction.
    """
    old, new = bounds(before), bounds(after)
    if len(old) != len(new):
        return None
    for (kind, o), (after_kind, n) in zip(old, new, strict=True):
        if kind != after_kind or o == n:
            continue
        if kind in (UPPER, TOL) and n > o:
            return f"{kind} {o} -> {n}"
        if kind == LOWER and n < o:
            return f"{kind} {o} -> {n}"
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
            if bounds(line):
                by_shape.setdefault(shape(line), line)
        for line in added:
            if not bounds(line):
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


def git(*args: str) -> str | None:
    """Trimmed stdout, or None when git failed."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def default_branch() -> str:
    """Best-effort default-branch name, without assuming a remote exists.

    `--base` defaulted to the literal "main" and an unresolvable ref exited 0,
    so on a repo whose default branch is `master` or `trunk` this check passed
    silently forever -- itself the "gate nobody can see fail" failure it
    exists to report.
    """
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[-1]
    for candidate in ("main", "master", "trunk"):
        if git("rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"):
            return candidate
    return "main"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base", default=None, help="ref to diff against (default: the default branch)"
    )
    parser.add_argument("--stdin", action="store_true", help="read a diff from stdin")
    parser.add_argument("--strict", action="store_true", help="exit 1 on a finding")
    args = parser.parse_args(argv)

    if args.stdin:
        diff = sys.stdin.read()
    else:
        base = args.base or default_branch()
        diff = git("diff", f"{base}...HEAD")
        if diff is None:
            # stderr, and a failure under --strict: a caller that asked for a
            # gate got no answer, and reporting "no loosenings" would be a
            # claim this run cannot support.
            print(f"Could not diff against {base}.", file=sys.stderr)
            return 1 if args.strict else 0

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
