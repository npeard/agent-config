#!/usr/bin/env python
"""Flag research questions that cannot be posed as one sentence.

Usage:
    python scripts/questions_lint.py QUESTIONS.md [--json]

A question unit is the first paragraph under a ``## Q<n>.`` heading or a
``- **Q<n>.<m>** ...`` bullet (continuation lines included). Rules:

- ``multi-question``: more than one sentence ends in ``?``.
- ``compound``: ``and`` joins a second interrogative clause, as in "how
  much does it improve, and what does one more channel buy?" (SMI Q1.1)
  or ends in "and by how much" / "and why" (SMI Q1, Q3). A noun list
  ("ridge regression and LightGBM included", SMI Q2.1) is not flagged.
- ``framing``: more than one non-question sentence before the question.
  One framing sentence is allowed (SMI Q2.3, Q4).

Report only; exit 0 on findings, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

HEADING = re.compile(r"^##\s+(Q\d+)\.")
BULLET = re.compile(r"^\s*-\s+\*\*(Q\d+(?:\.\d+)+)\*\*\s*(.*)")
ABBREVIATIONS = re.compile(r"\b(e\.g\.|i\.e\.|vs\.|et al\.)", re.IGNORECASE)
SENTENCE_BREAK = re.compile(r"(?<=[.?!])\s+(?=[A-Z(])")
COMPOUND = re.compile(
    r"\band (?:by how much|why|what|how|which|where|does|do|is|are|can)\b"
)
DOT = "\x00"


class Finding(NamedTuple):
    qid: str
    rule: str
    text: str


def sentences(paragraph: str) -> list[str]:
    """Split on sentence-final punctuation, sparing abbreviations."""
    protected = ABBREVIATIONS.sub(lambda m: m.group().replace(".", DOT), paragraph)
    return [s.replace(DOT, ".") for s in SENTENCE_BREAK.split(protected.strip())]


def units(text: str) -> list[tuple[str, str]]:
    """(qid, paragraph) for each heading paragraph and sub-question bullet."""
    found: list[tuple[str, str]] = []
    pending_heading: str | None = None
    current: list[str] | None = None  # [qid, text] being accumulated
    for line in [*text.splitlines(), ""]:
        bullet = BULLET.match(line)
        if bullet or HEADING.match(line) or not line.strip():
            if current:
                found.append((current[0], current[1]))
            current = None
        if bullet:
            current = [bullet.group(1), bullet.group(2)]
            continue
        heading = HEADING.match(line)
        if heading:
            pending_heading = heading.group(1)
        elif line.strip() and current:
            current[1] += " " + line.strip()
        elif line.strip() and pending_heading:
            current = [pending_heading, line.strip()]
            pending_heading = None
    return found


def lint(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for qid, paragraph in units(text):
        parts = sentences(paragraph)
        questions = [s for s in parts if s.endswith("?")]
        if len(questions) > 1:
            findings.append(Finding(qid, "multi-question", paragraph))
        if any(COMPOUND.search(q) for q in questions):
            findings.append(Finding(qid, "compound", paragraph))
        before = parts[: parts.index(questions[0])] if questions else parts
        if len(before) > 1:
            findings.append(Finding(qid, "framing", paragraph))
    return findings


def has_questions(text: str) -> bool:
    return any(HEADING.match(line) for line in text.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="a QUESTIONS.md file")
    parser.add_argument("--json", action="store_true", help="emit a JSON list")
    args = parser.parse_args(argv)
    try:
        text = Path(args.path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{args.path}: cannot read ({exc})", file=sys.stderr)
        return 2
    if not has_questions(text):
        print(f"{args.path}: no `## Q<n>.` headings found", file=sys.stderr)
        return 2
    findings = lint(text)
    if args.json:
        print(json.dumps([f._asdict() for f in findings], indent=2))
        return 0
    for f in findings:
        print(f"{f.qid}  {f.rule}  {f.text}")
    print(f"{len(findings)} findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
