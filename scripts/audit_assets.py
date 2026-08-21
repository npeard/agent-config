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
import tomllib
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


# Three shapes, because the house has three idioms and recognizing only some
# of them punishes a compliant asset. A first pass knew tables and fences
# only, and reported humanizer -- whose whole catalog is labelled before/after
# examples -- as evidence-free.
#
# A GFM table needs its delimiter row, or a line of prose containing pipes
# counts as evidence.
EVIDENCE_TABLE = re.compile(r"^\|.*\|[ \t]*$\n^\|[\s\-:|]+\|[ \t]*$", re.MULTILINE)
EVIDENCE_FENCE = re.compile(r"^```", re.MULTILINE)
EVIDENCE_EXAMPLE = re.compile(
    r"\*\*(?:Before|After|Flag|Prefer|Bad|Good|Example|Words to watch|Problem)\b",
    re.IGNORECASE,
)
EVIDENCE = (EVIDENCE_TABLE, EVIDENCE_FENCE, EVIDENCE_EXAMPLE)


def check_evidence(root: Path = REPO_ROOT) -> list[Finding]:
    """P2: built from real expertise, so it carries evidence.

    A proxy, and known to be one: presence of a table or a worked example is
    mechanical, whether the evidence behind it is real is not, and that
    judgement is left to skills/config-audit.

    Scoped to the skill directory rather than SKILL.md alone. A prototype
    scoped to SKILL.md reported humanizer as evidence-free when its
    35-pattern catalog is in patterns.md precisely because principle 3 says
    to push a catalog to a reference file -- a check that punishes compliance
    with one principle in the name of another is worse than none.
    """
    out = []
    for path in skill_files(root):
        texts = [p.read_text() for p in sorted(path.parent.glob("*.md"))]
        if not any(r.search(text) for text in texts for r in EVIDENCE):
            out.append(
                Finding(
                    2,
                    rel(path.parent, root),
                    "no table, code example or labelled worked example "
                    "anywhere in the skill directory; guidance with no "
                    "evidence structure reads as authoritative and cannot "
                    "be checked",
                )
            )
    return out


def check_script_help(root: Path = REPO_ROOT) -> list[Finding]:
    """P4: a script an agent must read to use has failed principle 3 while
    pretending to serve it."""
    out = []
    for path in script_files(root):
        if "ArgumentParser" not in path.read_text():
            out.append(
                Finding(
                    4,
                    rel(path, root),
                    "no argparse parser, so `--help` does not work and the "
                    "interface can only be learned by reading the source",
                )
            )
    return out


SCRIPT_REF = re.compile(r"scripts/([A-Za-z_][A-Za-z0-9_]*\.py)")
TASK_REF = re.compile(r"pixi run ([a-z][a-z0-9-]*)")
READ_THE_SOURCE = re.compile(
    r"\bread(?:ing|s)?\b[^.\n]{0,40}\bscripts/[A-Za-z_][A-Za-z0-9_]*\.py", re.IGNORECASE
)


def prose_files(root: Path = REPO_ROOT) -> list[Path]:
    """Everything that can name a script and so can name one that is gone."""
    candidates = [
        root / "CLAUDE.md",
        root / "README.md",
        *sorted((root / "skills").glob("*/*.md")),
    ]
    return [p for p in candidates if p.exists()]


def pixi_tasks(root: Path = REPO_ROOT) -> set[str]:
    """Names from `[tasks]` and from every `[feature.<name>.tasks]`.

    Reading only the top-level table reported six real tasks as dangling:
    this project keeps its dev-env tasks under a feature, which is idiomatic
    pixi and invisible to a top-level lookup.
    """
    path = root / "pixi.toml"
    if not path.exists():
        return set()
    data = tomllib.loads(path.read_text())
    names = set(data.get("tasks", {}))
    for feature in data.get("feature", {}).values():
        names |= set(feature.get("tasks", {}))
    return names


def check_script_references(root: Path = REPO_ROOT) -> list[Finding]:
    """P4: a named script or task must resolve, and prose must name the
    command rather than the source."""
    have = {p.name for p in script_files(root)}
    tasks = pixi_tasks(root)
    out = []
    for path in prose_files(root):
        text = path.read_text()
        asset = rel(path, root)
        for name in sorted(set(SCRIPT_REF.findall(text)) - have):
            out.append(Finding(4, asset, f"names scripts/{name}, which does not exist"))
        for name in sorted(set(TASK_REF.findall(text)) - tasks):
            out.append(
                Finding(
                    4,
                    asset,
                    f"names `pixi run {name}`, which is not a task in pixi.toml",
                )
            )
        for hit in READ_THE_SOURCE.findall(text):
            out.append(
                Finding(
                    4,
                    asset,
                    "instructs reading a script rather than running it: "
                    f'"{hit.strip()}"',
                )
            )
    return out


# This file's own name. Every pattern below appears here as data, so without
# an explicit exclusion the check reports itself and the finding can never be
# resolved. Moving the patterns to a data file would fix that and make the
# script unusable when copied, which is a worse trade.
SELF = Path(__file__).name

UNTRUSTED_SOURCES = {
    "transcript": re.compile(r"\.claude/projects|\.jsonl"),
    "network": re.compile(r"\burllib\b|\brequests\b|\bsocket\b|https?://"),
    "foreign-manifest": re.compile(
        r"pixi\.toml|pyproject\.toml|package\.json|Cargo\.toml|Makefile"
    ),
    "shell-out": re.compile(r"osascript|shell=True|os\.system"),
}

# `print(` of anything that is not a bare string literal. The negative
# lookahead for `=` keeps a keyword argument (`print(file=...)`) from counting
# as emitted content.
EMIT_SINKS = {
    "agent-context": re.compile(r"additionalContext"),
    "shell-argument": re.compile(r"osascript|shell=True|os\.system"),
    "stdout-nonliteral": re.compile(
        r"print\(\s*(?:f[\"']|[A-Za-z_][A-Za-z0-9_]*\b(?!\s*=))"
    ),
}


def check_read_and_emit(root: Path = REPO_ROOT) -> list[Finding]:
    """P5: enumerate where content this repo did not author reaches agent
    context, a shell, or stdout an agent reads.

    Reports the conjunction and never a verdict. Whether a path is
    exploitable, and what the right trust boundary is, is judgement --
    skills/config-audit's job. Enumerating the surface is this check's job.

    Deliberately wide: `shell-out` is both a source and a sink, because
    passing text to osascript is simultaneously the untrusted read and the
    dangerous emission. If a future audit's P5 section is mostly re-reading
    ledger entries, narrow this to agent-context and shell-argument and drop
    plain stdout.
    """
    out = []
    for path in [*script_files(root), *hook_files(root)]:
        if path.name == SELF:
            continue
        text = path.read_text()
        sources = sorted(k for k, r in UNTRUSTED_SOURCES.items() if r.search(text))
        sinks = sorted(k for k, r in EMIT_SINKS.items() if r.search(text))
        if sources and sinks:
            out.append(
                Finding(
                    5,
                    rel(path, root),
                    f"reads {'/'.join(sources)} and emits via {'/'.join(sinks)}; "
                    "state the trust boundary in a comment, or ledger why none "
                    "is needed",
                )
            )
    return out


# Extended by later tasks. Order here is the order findings are collected in;
# `audit` sorts, so it does not affect output.
CHECKS = (
    check_trigger_shaped,
    check_budgets,
    check_evidence,
    check_script_help,
    check_script_references,
    check_read_and_emit,
)


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
