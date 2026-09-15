#!/usr/bin/env python
"""Decide whether tonight is worth waking a model for, and stage the reason.

This is the gate, not the improvement. It runs the instruments that already
exist -- friction, toolgaps, audit -- and exits without spending a token
unless one of them crossed a bar it owns. When something did cross, it writes
a brief to a file and says so; a model reads that brief in a fresh session and
runs the `reflect` skill against it.

Why a gate rather than a nightly reflect pass: asked what was frustrating, a
model always answers. SkillOpt measured what that costs when the answer is
accepted without a check -- an ungated self-improvement loop on SearchQA fell
from 0.554 to 0.026 over five nights, learning to emit the document title
verbatim, while the gated twin rejected every one of those edits and lost
nothing. This script cannot grade a proposed config edit, so the gate it does
enforce is cheaper and blunter: only *recurring measured* friction gets a
session at all, and the human reviews whatever comes out.

Stages 1-2 spend no model context by design. A quiet night costs one line in
a log.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRIEF = REPO_ROOT / ".nightly-brief"
LOG = REPO_ROOT / ".nightly-log"


def instrument(name: str, args: list[str]) -> dict | None:
    """Run one instrument and parse its JSON, or None if it could not run.

    A failed instrument is not a reason to wake a model -- it is a reason to
    say so in the log and stop. Treating a crash as "no friction found" would
    make the loop go quietly blind, which is the failure friction-ledger's
    count_at_decision rule exists to prevent one level up.
    """
    script = REPO_ROOT / "scripts" / f"{name}.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=REPO_ROOT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Exit code is deliberately ignored: audit returns 1 when it has findings,
    # which is a result rather than a failure. Only unparsable output means
    # the instrument did not run.
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def reasons(friction: dict | None, audit: dict | None, gaps: dict | None) -> list[str]:
    """Why tonight is worth a session. Empty means it is not.

    Each entry names the instrument and what it found, because the brief is
    read by a model with no other context and "something crossed a bar" is
    not a task.
    """
    out = []
    if friction is None:
        return []
    n = friction.get("actionable_count", 0)
    if n:
        classes = ", ".join(c.get("name", "?") for c in friction.get("actionable", []))
        out.append(f"friction: {n} class(es) over the bar and undecided -- {classes}")
    # Only live findings count. A warning is a prompt to a human in the room
    # and this loop has none, so --strict promotes them; that is why the audit
    # is invoked with it and why a warning appearing here is a failure.
    if audit and audit.get("findings"):
        assets = ", ".join(f["asset"] for f in audit["findings"])
        out.append(f"audit: {len(audit['findings'])} live finding(s) -- {assets}")
    if gaps and gaps.get("gaps"):
        out.append(f"toolgaps: missing {', '.join(gaps['gaps'])}")
    return out


def write_brief(found: list[str]) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    BRIEF.write_text(
        "\n".join(
            [
                f"# Nightly brief, {stamp}",
                "",
                "An instrument crossed a bar it owns. Run the `reflect` skill",
                "against the item(s) below in a fresh session: diagnose the",
                "cause before choosing a tier, and record the decision in",
                "friction-ledger.toml.",
                "",
                "Propose a diff on a branch. Do not merge it -- a human reads",
                "it. One proposal, not one per item.",
                "",
                *(f"- {line}" for line in found),
                "",
                "Then delete this file, which is what allows the next night to",
                "stage anything.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def log(message: str) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp}\t{message}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the decision without writing a brief or a log line",
    )
    args = parser.parse_args(argv)

    if BRIEF.is_file():
        # One unreviewed proposal at a time, and the brief's own existence is
        # the whole mechanism -- there is no count to configure, because the
        # limit that matters is "a human has not read the last one yet".
        # Unreviewed drift is the second failure mode after self-confirming
        # edits: a loop that stages seven proposals in a week has produced a
        # backlog nobody reads, which is the same as producing nothing except
        # that it also edited the config seven times. Not an error.
        message = f"held: {BRIEF.name} still pending review"
        print(message)
        if not args.dry_run:
            log(message)
        return 0

    friction = instrument("friction", ["--json"])
    if friction is None:
        message = "stopped: friction.py did not run"
        print(message)
        if not args.dry_run:
            log(message)
        return 1

    audit = instrument("audit_assets", ["--json", "--strict"])
    gaps = instrument("toolgaps", ["--json"])
    found = reasons(friction, audit, gaps)

    if not found:
        message = (
            f"quiet: nothing over the bar (window from {friction.get('window_since')})"
        )
        print(message)
        if not args.dry_run:
            log(message)
        return 0

    print("\n".join(found))
    if args.dry_run:
        return 0
    write_brief(found)
    log(f"staged: {len(found)} item(s); {BRIEF.name} written")
    print(f"\nWrote {BRIEF}. A model reads it next; nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
