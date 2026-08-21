#!/usr/bin/env python
"""Audit this repo's own assets against the five agent-asset principles.

Specific to claude-config, like register_hooks.py and unlike the other
scripts here: it knows this repo's layout (skills/, scripts/, hooks/,
CLAUDE.md) rather than describing a capability every project has, so it is
not meant to be copied elsewhere verbatim.

Reports and never fixes. The fix for a principle violation is usually a
judgement call about whether the asset should change or the exception should
be recorded, which is what skills/config-audit exists to make.

The context ceilings live here rather than in tests/test_context_budget.py so
that one number has one definition: the test imports them and remains the
gate that fails the build, while this script is the report the audit reads.

Usage:
    python scripts/audit_assets.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Measured at the time of writing plus deliberately tight headroom. Raising
# one of these should feel heavier than adding a sentence, which is the point.
CLAUDE_MD_MAX_WORDS = 1250
SKILL_BODY_MAX_WORDS = 2000
SKILL_DESCRIPTION_MAX_WORDS = 60

# The openers superpowers:writing-skills already prescribes. Tracking that
# skill rather than inventing a rule here: a check that disagreed with the
# authoring guidance would be worse than no check at all.
TRIGGER_OPENERS = ("use when", "use this when", "use for", "use before", "trigger")


@dataclass(frozen=True)
class Finding:
    principle: int
    asset: str
    detail: str

    @property
    def key(self) -> str:
        """Ledger identity. An exception is granted to an asset for one
        principle, not to an asset wholesale."""
        return f"{self.asset}::P{self.principle}"


def words(text: str) -> int:
    return len(text.split())


def frontmatter(text: str) -> str | None:
    """The YAML block between the leading `---` fences, if any."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else None


def description(text: str) -> str | None:
    """The description value, including folded continuation lines.

    A regex capturing to end-of-line reads `description: >` as the single
    word ">" and lets an arbitrarily long description through the budget.
    Searching the whole file rather than the frontmatter would also measure
    a body line that merely starts with "description:".
    """
    block = frontmatter(text)
    if block is None:
        return None
    lines = block.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        # A folded or literal scalar puts the text on the indented lines
        # that follow; a plain scalar may also wrap onto them.
        parts = [] if value in (">", "|", ">-", "|-") else [value]
        for cont in lines[i + 1 :]:
            if not cont[:1].isspace() or not cont.strip():
                break
            parts.append(cont.strip())
        return " ".join(parts)
    return None


def skill_files(root: Path = REPO_ROOT) -> list[Path]:
    return sorted((root / "skills").glob("*/SKILL.md"))


def script_files(root: Path = REPO_ROOT) -> list[Path]:
    return sorted((root / "scripts").glob("*.py"))


def hook_files(root: Path = REPO_ROOT) -> list[Path]:
    return sorted((root / "hooks").glob("*.py"))


def rel(path: Path, root: Path = REPO_ROOT) -> str:
    return path.relative_to(root).as_posix()


def first_clause(text: str) -> str:
    """Up to the first sentence- or clause-ending mark.

    The description is read top-down, so a trigger that arrives after a
    leading sentence is a trigger the reader reaches second.
    """
    return re.split(r"[,.;:]|\s--\s|\s-\s", text, maxsplit=1)[0].strip()


def check_trigger_shaped(root: Path = REPO_ROOT) -> list[Finding]:
    """P1: the description is the trigger."""
    out = []
    for path in skill_files(root):
        value = description(path.read_text())
        if not value:
            out.append(Finding(1, rel(path, root), "no description in frontmatter"))
            continue
        clause = first_clause(value)
        if not clause.lower().startswith(TRIGGER_OPENERS):
            out.append(
                Finding(
                    1,
                    rel(path, root),
                    f'description leads with "{clause}" rather than a trigger '
                    f"clause; expected one of {', '.join(TRIGGER_OPENERS)}",
                )
            )
    return out


def check_budgets(root: Path = REPO_ROOT) -> list[Finding]:
    """P3: spend context wisely."""
    out = []
    n = words((root / "CLAUDE.md").read_text())
    if n > CLAUDE_MD_MAX_WORDS:
        out.append(
            Finding(
                3, "CLAUDE.md", f"{n} words, over the {CLAUDE_MD_MAX_WORDS} ceiling"
            )
        )
    for path in skill_files(root):
        text = path.read_text()
        n = words(text)
        if n > SKILL_BODY_MAX_WORDS:
            out.append(
                Finding(
                    3,
                    rel(path, root),
                    f"body {n} words, over the {SKILL_BODY_MAX_WORDS} ceiling",
                )
            )
        value = description(text)
        if value and words(value) > SKILL_DESCRIPTION_MAX_WORDS:
            out.append(
                Finding(
                    3,
                    rel(path, root),
                    f"description {words(value)} words, over the "
                    f"{SKILL_DESCRIPTION_MAX_WORDS} ceiling; descriptions are "
                    "listed in every session, so this is always-loaded cost",
                )
            )
    return out


# Extended by later tasks. Order here is the order findings are collected in;
# `audit` sorts, so it does not affect output.
CHECKS = (check_trigger_shaped, check_budgets)


def audit(root: Path = REPO_ROOT) -> list[Finding]:
    found: list[Finding] = []
    for check in CHECKS:
        found.extend(check(root))
    return sorted(found, key=lambda f: (f.principle, f.asset))


def render(findings: list[Finding]) -> None:
    if not findings:
        print("No principle violations.")
        return
    print(f"{len(findings)} finding(s):\n")
    for f in findings:
        print(f"  P{f.principle}  {f.asset}")
        print(f"        {f.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit this repo's assets against the five agent-asset principles."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output, for the config-audit skill",
    )
    args = parser.parse_args(argv)
    findings = audit()
    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings]}, indent=2))
    else:
        render(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
