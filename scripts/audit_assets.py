#!/usr/bin/env python
"""Audit this repo's own assets against the five agent-asset principles.

Specific to agent-config, like register_hooks.py and unlike the other
scripts here: it knows this repo's layout (skills/, scripts/, hooks/,
AGENTS.md) rather than describing a capability every project has, so it is
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
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "audit-ledger.toml"

# Two bands per budget. The lower one warns and does not fail; the upper one
# fails. Until 2026-09-15 there was one band and it failed, on the reasoning
# that raising a ceiling "should feel heavier than adding a sentence" -- and
# that is still true of the *fail* band, which is why one still exists.
#
# What changed is calibration against the practice these assets imitate.
# Anthropic's shipped superpowers skills run 344-4823 words (median 1059), so
# three of fourteen would have breached the old 2000 body ceiling, and their
# own writing-skills reference is 5803 words -- 290% of the old reference
# ceiling. A gate stricter than the work it models rejects good assets.
#
# The countervailing measurement, kept here because it is the reason the warn
# band exists at all: this repo's median SKILL.md was 1294 words against
# superpowers' 1059. They hold a *lower* median under a *higher* ceiling. So
# the fail band moves to match them and the warn band stays at the old
# numbers, where it reports the cost without refusing the asset. If the median
# climbs after this, the warn band is being ignored and the raise was wrong.
AGENTS_MD_WARN_WORDS = 1500
AGENTS_MD_MAX_WORDS = 2000
SKILL_BODY_WARN_WORDS = 2000
SKILL_BODY_MAX_WORDS = 4800
SKILL_DESCRIPTION_MAX_WORDS = 60

# A reference file loads on demand, which is what makes it the cheap tier --
# but nothing measured one, so moving prose out of SKILL.md turned a measured
# cost into an invisible one, and that was the *sanctioned* way to get under
# the body ceiling. Verified before this existed: a 17-word SKILL.md beside a
# 50,006-word catalog.md produced no finding.
# The same numbers as the body, because a file the reader is told to read
# costs what a body costs. The tier is cheaper for being conditional, not for
# being unbounded.
REFERENCE_WARN_WORDS = 2000
REFERENCE_MAX_WORDS = 5800

# What one invocation actually costs: the body plus every reference an
# imperative step tells the reader to read. Measured this way, three of the
# seven skills here exceeded the body ceiling while the gate reported all
# seven comfortably under -- humanizer at 4878 words, 244% of it.
#
# Deliberately larger than the body ceiling. Measured against 2000 this would
# report standards-and-spec-review (803 + 1390) and config-audit (1165 +
# 1153), whose split into a body plus one reference is exactly what principle
# 3 prescribes -- and a check that punishes compliance with one principle in
# the name of another is worse than no check (AGENT_ASSET_PRINCIPLES.md's
# binding rule 2). Derived rather than picked, so it cannot be tuned to
# exempt an asset: a skill may cost one body and one full reference per
# invocation, and needing more than that means a second catalog should be
# loading on demand instead.
SKILL_EFFECTIVE_WARN_WORDS = SKILL_BODY_WARN_WORDS + REFERENCE_WARN_WORDS
SKILL_EFFECTIVE_MAX_WORDS = SKILL_BODY_MAX_WORDS + REFERENCE_MAX_WORDS

# An imperative step naming a markdown file: "Read `patterns.md`", "read
# CODING_STANDARDS.md next to this file". The verb has to govern the name, so
# config-audit's "defined in `AGENT_ASSET_PRINCIPLES.md`, read on demand" does
# not match -- that sentence says the read is conditional, and charging for it
# would be the punishing-compliance failure again. Same shape as
# READ_THE_SOURCE below, which reads the same instruction for scripts.
REQUIRED_READ = re.compile(
    r"\bread\b[^.\n]{0,40}?`?([A-Za-z0-9_.-]+\.md)`?", re.IGNORECASE
)

# The openers superpowers:writing-skills already prescribes. Tracking that
# skill rather than inventing a rule here: a check that disagreed with the
# authoring guidance would be worse than no check at all.
TRIGGER_OPENERS = ("use when", "use this when", "use for", "use before", "trigger")


@dataclass(frozen=True)
class Finding:
    principle: int
    asset: str
    detail: str
    # A warning reports a cost without refusing the asset: it prints, and it
    # does not contribute to the exit code. Defaulted so every existing
    # construction stays a failure -- a check that became advisory by
    # accident is worse than no check.
    #
    # Deliberately not ledgered. The ledger suppresses a finding until the
    # asset changes, which is right for a judgement that was made once; a
    # warning is re-asked every run on purpose, because the question it puts
    # ("is this duplicated, does it earn its cost, should it be a new asset")
    # has a different answer as the asset grows.
    warning: bool = False

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


def skill_texts(root: Path = REPO_ROOT) -> list[tuple[Path, str]]:
    """Every SKILL.md with its contents, read once.

    Three checks want the same text -- the trigger clause, the budgets, and
    the overlap scan -- and each walking skill_files itself meant the same
    file was read three times and the same two lines written three times.
    """
    return [(path, path.read_text(encoding="utf-8")) for path in skill_files(root)]


def first_clause(text: str) -> str:
    """Up to the first sentence- or clause-ending mark.

    The description is read top-down, so a trigger that arrives after a
    leading sentence is a trigger the reader reaches second.
    """
    return re.split(r"[,.;:]|\s--\s|\s-\s", text, maxsplit=1)[0].strip()


def check_trigger_shaped(root: Path = REPO_ROOT) -> list[Finding]:
    """P1: the description is the trigger."""
    out = []
    for path, text in skill_texts(root):
        value = description(text)
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


# Words every description shares by construction. Without removing them the
# mandatory trigger opener is itself overlap, every pair trips, and the check
# reports nothing usable.
OVERLAP_STOPWORDS = frozenset(
    {
        # Structural words, plus the trigger opener every description shares.
        "and",
        "are",
        "the",
        "that",
        "this",
        "with",
        "when",
        "for",
        "from",
        "into",
        "not",
        "use",
        "used",
        "using",
        "its",
        "their",
    }
)

# Set from measurement, not taste. Across the seven skills present when this
# was written the highest pairwise similarity is 0.148 --
# standards-and-spec-review against workflow-orchestration, an adjacency that
# is intentional and documented -- so 0.35 leaves that alone while still
# catching a genuine near-duplicate. Calibrated on seven skills, so it may not
# hold at twenty; if a real pair ever trips it, read the pair before touching
# the number. `max_overlap` prints the current figure.
OVERLAP_THRESHOLD = 0.35

# Joins the two halves of a pairwise finding's asset. "+" cannot appear in
# a skill directory name, so splitting on it is unambiguous.
PAIR_SEP = "+"


def content_words(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z]+", text.lower())
        if w not in OVERLAP_STOPWORDS and len(w) > 2
    }


def overlap_pairs(root: Path = REPO_ROOT) -> list[tuple[float, str, str]]:
    """Every description pair and its Jaccard score, most similar first.

    One scan with two consumers: `check_overlap` filters it by the threshold,
    `max_overlap` takes its head. An earlier version had each walk the pairs
    itself, which was twenty duplicated lines earning nothing.
    """
    described = []
    for path, text in skill_texts(root):
        value = description(text)
        if value:
            described.append((rel(path.parent, root), content_words(value)))
    scored = []
    for i, (a_name, a_words) in enumerate(described):
        for b_name, b_words in described[i + 1 :]:
            union = a_words | b_words
            if not union:
                continue
            first, second = sorted((a_name, b_name))
            scored.append((len(a_words & b_words) / len(union), first, second))
    return sorted(scored, reverse=True)


def max_overlap(root: Path = REPO_ROOT) -> tuple[float, str, str]:
    """The most similar pair, as (score, asset, asset).

    Exposed so a test can bound the measurement with a literal rather than
    against OVERLAP_THRESHOLD -- comparing it to the threshold is implied by
    `check_overlap` returning nothing, and both keep passing if the threshold
    is raised to hide a real pair.
    """
    pairs = overlap_pairs(root)
    return pairs[0] if pairs else (0.0, "", "")


def check_overlap(root: Path = REPO_ROOT) -> list[Finding]:
    """P1: two triggers a reader would have to choose between.

    Reports the pair and its score; it never picks a winner. Which of two
    overlapping skills should narrow its trigger, or whether they should
    merge, is the judgement `reflect`'s boundary-sentence test exists for.

    Keyed on BOTH assets, joined by PAIR_SEP. Keying it on one would break
    the ledger two ways: A-overlaps-B and A-overlaps-C would collide on one
    key, so reviewing one silently suppresses the other, and `asset_sha`
    would cover only one side -- rewriting the *other* skill's description to
    be near-identical would leave the exception in force.
    """
    return [
        Finding(
            1,
            f"{first}{PAIR_SEP}{second}",
            f"trigger overlaps at {score:.2f} (threshold "
            f"{OVERLAP_THRESHOLD:.2f}); a reader has to choose between them "
            "and will sometimes choose wrong",
        )
        for score, first, second in overlap_pairs(root)
        if score >= OVERLAP_THRESHOLD
    ]


def reference_files(skill_dir: Path) -> list[Path]:
    """Every markdown file in a skill directory other than SKILL.md.

    rglob, because references/<file>.md is the layout
    superpowers:writing-skills prescribes and a top-level scan would miss it.
    Markdown only: a code sample is evidence (see check_evidence), not prose
    the reader is charged for.
    """
    return [p for p in sorted(skill_dir.rglob("*.md")) if p.name != "SKILL.md"]


def required_references(path: Path, text: str) -> list[Path]:
    """The reference files this SKILL.md tells the reader to read outright.

    Fences are stripped for the same reason as in check_script_references's
    READ_THE_SOURCE: inside a fence, "Read `x.md`" is an illustration of the
    instruction rather than the instruction.

    A named file that is not in the skill directory is not charged. A skill
    may point at the *project's* file of the same name, and AGENTS.md has its
    own ceiling already.
    """
    named = {m.group(1).lower() for m in REQUIRED_READ.finditer(unfenced(text))}
    return [p for p in reference_files(path.parent) if p.name.lower() in named]


def effective_words(path: Path, text: str) -> int:
    """What one invocation of this skill costs: body plus required references."""
    return words(text) + sum(
        words(ref.read_text(encoding="utf-8"))
        for ref in required_references(path, text)
    )


# What the warn band asks. Not "trim this": the useful question is whether the
# words are duplicated, and "useless" is not mechanically definable, so this
# routes the judgement to the skill that owns the cause taxonomy and the tier
# ladder rather than deciding it in a checker.
WARN_PROMPT = (
    "not a failure -- review before adding more: (1) is this duplicated prose "
    "or duplicated intent with an existing asset, in which case consolidate "
    "via the reflect skill's redundancy check rather than adding; (2) does it "
    "add context or reinforce behaviour that decays without it, or neither; "
    "(3) does it belong in a new skill, a reference file, a hook or a script "
    "instead of here"
)


def budget(
    asset: str, n: int, warn: int, fail: int, principle: int, detail: str
) -> list[Finding]:
    """The finding a measured asset owes its budget, if any.

    One function for all four budgets so the two-band comparison is written
    once: four copies of `if n > fail: ... elif n > warn: ...` is four places
    for the bands to drift apart, and a budget silently checked against the
    wrong band is the failure this whole check exists to prevent.
    """
    if n > fail:
        return [Finding(principle, asset, f"{detail}, over the {fail} ceiling")]
    if n > warn:
        return [
            Finding(
                principle,
                asset,
                f"{detail}, over the {warn} warn threshold ({fail} fails); "
                f"{WARN_PROMPT}",
                warning=True,
            )
        ]
    return []


def check_budgets(root: Path = REPO_ROOT) -> list[Finding]:
    """P3: spend context wisely."""
    out = []
    # Guarded like prose_files and pixi_tasks. Unguarded, `pixi run audit` on a
    # tree where AGENTS.md is absent tracebacks instead of reporting the P4
    # dangling references that rename produces -- the audit failing exactly
    # when it has something to say.
    agents_md = root / "AGENTS.md"
    n = words(agents_md.read_text(encoding="utf-8")) if agents_md.is_file() else 0
    out += budget(
        "AGENTS.md", n, AGENTS_MD_WARN_WORDS, AGENTS_MD_MAX_WORDS, 3, f"{n} words"
    )
    for path, text in skill_texts(root):
        n = words(text)
        out += budget(
            rel(path, root),
            n,
            SKILL_BODY_WARN_WORDS,
            SKILL_BODY_MAX_WORDS,
            3,
            f"body {n} words",
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
        for ref in reference_files(path.parent):
            n = words(ref.read_text(encoding="utf-8"))
            out += budget(
                rel(ref, root),
                n,
                REFERENCE_WARN_WORDS,
                REFERENCE_MAX_WORDS,
                3,
                f"reference {n} words (an on-demand file is the cheap tier, "
                "not a free one)",
            )
        required = required_references(path, text)
        total = effective_words(path, text)
        named = ", ".join(ref.name for ref in required)
        out += budget(
            rel(path.parent, root),
            total,
            SKILL_EFFECTIVE_WARN_WORDS,
            SKILL_EFFECTIVE_MAX_WORDS,
            3,
            f"{total} words per invocation (SKILL.md plus {named}, which its "
            "own steps say to read; make a reference genuinely conditional or "
            "split it)",
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

# A worked artifact beside the prose counts as evidence on its own.
EVIDENCE_SUFFIXES = frozenset(
    {".py", ".js", ".ts", ".sh", ".tex", ".json", ".yaml", ".yml", ".toml", ".csv"}
)


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
        # rglob, not glob: the finding text and sha() both say "anywhere in the
        # skill directory", and references/<file>.md is the layout
        # superpowers:writing-skills prescribes -- reporting such a skill as
        # evidence-free is the punishing-compliance failure binding rule 2 names.
        files = [
            f
            for f in sorted(path.parent.rglob("*"))
            if f.is_file() and "__pycache__" not in f.parts
        ]
        # A non-markdown file in a skill directory is a worked artifact -- a
        # code sample or a fixture -- and counts on its own. sha() already
        # hashes every file for this asset and says so; scanning only markdown
        # here meant the two disagreed about what "the skill directory" holds,
        # so a skill whose evidence is examples/demo.py was a false P2.
        # A named set, not "any non-markdown file": the latter meant a single
        # .DS_Store -- which macOS supplies for free on a Finder visit --
        # silently exempted a skill from the evidence check.
        if any(f.suffix in EVIDENCE_SUFFIXES for f in files):
            continue
        # Only markdown is read. An earlier version read every file it had
        # listed, so one .png or .DS_Store in a skill directory raised
        # UnicodeDecodeError -- and since `audit` is a dependency of
        # `pixi run all`, a stray binary broke the whole build. Presence is
        # what qualifies a worked artifact above; text is only needed for the
        # prose patterns below.
        texts = [f.read_text(encoding="utf-8") for f in files if f.suffix == ".md"]
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
        if "ArgumentParser" not in path.read_text(encoding="utf-8"):
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


FENCED_BLOCK = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)


def unfenced(text: str) -> str:
    """`text` with fenced code blocks removed.

    Applied to READ_THE_SOURCE only. That check is about an instruction to
    the reader, and inside a fence the same sentence is an illustration --
    AGENT_ASSET_PRINCIPLES.md documents this very anti-pattern with a `Flag:`
    example, and a check that cannot tell a counter-example from a directive
    reports the file teaching the rule as breaking it.

    Not applied to the name-resolution checks: a script path or task name in
    a fence is still a pointer a reader will follow, and README's command
    block is exactly that.
    """
    return FENCED_BLOCK.sub("", text)


def prose_files(root: Path = REPO_ROOT) -> list[Path]:
    """Everything that can name a script and so can name one that is gone.

    The ledgers are included, and not as an afterthought: audit-ledger.toml's
    own header named `python scripts/audit_assets.py --sha` -- the exact P4
    anti-pattern this check exists to find -- in the one file the check could
    not see.
    """
    candidates = [
        root / "AGENTS.md",
        root / "README.md",
        root / "audit-ledger.toml",
        root / "friction-ledger.toml",
        # rglob: top-level-only was the same depth bug fixed in check_evidence.
        # A dangling scripts/... reference inside skills/*/references/*.md was
        # invisible, latent only because every reference file in this repo
        # currently sits at its skill's top level.
        *sorted((root / "skills").rglob("*.md")),
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
    data = tomllib.loads(path.read_text(encoding="utf-8"))
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
        text = path.read_text(encoding="utf-8")
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
        for hit in READ_THE_SOURCE.findall(unfenced(text)):
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
LAYOUT_HEADING = "## Layout"


def layout_section(text: str) -> str:
    """The part of README where naming an asset documents it.

    The finding below says "add a Layout entry", so the check has to mean
    that: a bare substring anywhere satisfied it, including inside a fence,
    and a README whose only mention of a skill was `ls skills/bloated` in a
    command block passed. Fences go for the same reason as in unfenced() --
    inside one, a name is an example of usage rather than a description of
    the asset.

    With no Layout heading the whole file is used. A missing section is a
    README problem, and a check that reports every asset at once is one
    nobody reads.
    """
    body = unfenced(text)
    start = body.find(LAYOUT_HEADING)
    if start == -1:
        return body
    section = body[start:]
    end = section.find("\n## ", len(LAYOUT_HEADING))
    return section if end == -1 else section[:end]


def documented(region: str, path: Path, root: Path) -> bool:
    """Whether `region` names this asset, rather than one it is a substring of.

    A plain `in` test let a future `scripts/ascii.py` pass on README's
    existing mention of `check_ascii.py`, so the check would have stayed
    silent about a script that really was undocumented.
    """
    for candidate in (rel(path, root), path.name):
        if re.search(rf"(?<![\w./-]){re.escape(candidate)}(?![\w-])", region):
            return True
    return False


def check_asset_documented(root: Path = REPO_ROOT) -> list[Finding]:
    """P4: an asset the README does not name is one you must read the tree to find.

    The reverse direction of check_script_references, which only asks whether a
    *named* script exists. Nothing asked the other way, so an asset could ship
    undocumented and be invisible to every gate here -- and it had:
    promotion-check.py, task-list.py and skills/quantikz were named nowhere in
    the Layout section, one of them for months.

    Matched on the bare name as well as the path, because README groups the
    generic scripts into one bullet that lists filenames rather than paths.
    """
    readme = root / "README.md"
    if not readme.is_file():
        return []
    region = layout_section(readme.read_text(encoding="utf-8"))
    assets = [*hook_files(root), *script_files(root)]
    assets += [d for d in sorted((root / "skills").glob("*")) if d.is_dir()]
    out = []
    for path in assets:
        if documented(region, path, root):
            continue
        out.append(
            Finding(
                4,
                rel(path, root),
                "not named in README.md's Layout section, so it can only be "
                "discovered by reading the tree; add a Layout entry saying "
                "why it exists",
            )
        )
    return out


SELF = Path(__file__).name

UNTRUSTED_SOURCES = {
    "transcript": re.compile(r"\.claude/projects|\.jsonl"),
    "network": re.compile(r"\burllib\b|\brequests\b|\bsocket\b|https?://"),
    "foreign-manifest": re.compile(
        r"pixi\.toml|pyproject\.toml|package\.json|Cargo\.toml|Makefile"
    ),
    "shell-out": re.compile(r"osascript|shell=True|os\.system"),
    "subprocess": re.compile(r"subprocess\.(?:run|check_output|Popen)"),
}

# Split by how foreign the content is, not by how loud the sink is. Narrowing
# to high-severity sinks alone was the obvious move and the wrong one: it would
# have exempted friction.py, whose 400 characters of raw session transcript go
# to plain stdout -- and a script's stdout is read by the agent that ran it, so
# for genuinely foreign content stdout is not a weak sink at all.
#
# Content this repo did not author and cannot vouch for. Any emission counts.
FOREIGN_SOURCES = frozenset({"transcript", "network"})

# Content from a file the user cloned deliberately, or from this repo's own git.
# Real surface, but weak enough that emitting it to a terminal is not worth a
# standing ledger entry; it counts only where an instruction could be obeyed.
# This is what keeps preflight.py and toolgaps.py -- which emit check names and
# statuses rather than anything they read -- out of the report.
WEAK_SOURCES = frozenset({"foreign-manifest", "subprocess", "shell-out"})

# Where an instruction inside the content could actually be acted on.
HIGH_SINKS = frozenset({"agent-context", "shell-argument"})

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
        text = path.read_text(encoding="utf-8")
        sources = sorted(k for k, r in UNTRUSTED_SOURCES.items() if r.search(text))
        sinks = sorted(k for k, r in EMIT_SINKS.items() if r.search(text))
        # A source is always required. Keyed on the sink alone this reported
        # promotion-check.py, which emits into agent context but reads nothing
        # from outside the repo at all.
        foreign = set(sources) & FOREIGN_SOURCES
        weak = set(sources) & WEAK_SOURCES
        high = set(sinks) & HIGH_SINKS
        if not (sinks and (foreign or (weak and high))):
            continue
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
    check_overlap,
    check_budgets,
    check_evidence,
    check_script_help,
    check_script_references,
    check_asset_documented,
    check_read_and_emit,
)


def audit(root: Path = REPO_ROOT) -> list[Finding]:
    """Every finding, failures and warnings together.

    Callers that gate on the result must split them -- `partition` does it in
    one place, and every caller uses that rather than re-deriving the
    predicate. Returning only failures here was the obvious alternative and is
    wrong: the config-audit skill reads this to see the whole picture, and a
    warning invisible to the audit's own reader is a warning that cannot be
    acted on.
    """
    found: list[Finding] = []
    for check in CHECKS:
        found.extend(check(root))
    return sorted(found, key=lambda f: (f.principle, f.asset))


def partition(
    findings: list[Finding], strict: bool = False
) -> tuple[list[Finding], list[Finding]]:
    """(failures, warnings). `strict` promotes every warning to a failure."""
    if strict:
        return list(findings), []
    return [f for f in findings if not f.warning], [f for f in findings if f.warning]


def render(findings: list[Finding]) -> None:
    if not findings:
        print("No principle violations.")
        return
    print(f"{len(findings)} finding(s):\n")
    for f in findings:
        print(f"  P{f.principle}  {f.asset}")
        print(f"        {f.detail}")


def render_warnings(findings: list[Finding]) -> None:
    """Warnings print under their own heading and after the failures.

    Separated in the output as well as in the exit code, because a warning
    listed among failures reads as one -- and a reader who learns that some
    lines under "finding(s)" do not fail the run stops trusting the ones that
    do.
    """
    if not findings:
        return
    print(f"\n{len(findings)} warning(s) -- these do not fail the audit:\n")
    for f in findings:
        print(f"  P{f.principle}  {f.asset}")
        print(f"        {f.detail}")


# `note` is required for the same reason as `asset_sha`: an entry that
# suppresses a finding forever with no recorded reason is worse than no entry,
# because it reads as decided.
REQUIRED_LEDGER_FIELDS = frozenset(
    {"asset", "principle", "date", "cause", "outcome", "asset_sha", "note"}
)


def sha(path: Path) -> str | None:
    """Content hash of a file, or of a directory's files.

    Directories are handled because P2 findings name one. Every regular file
    counts, not just `*.md`: a skill's evidence can be a code sample or a
    fixture, and hashing only markdown left the ledger's "expires when the
    file changes" promise false for those. Relative paths go into the digest
    alongside contents, so renaming or deleting a file expires the exception
    too. __pycache__ is excluded because it is a build artifact, not content.
    """
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if path.is_dir():
        h = hashlib.sha256()
        for child in sorted(path.rglob("*")):
            # Dotfiles and caches are excluded, not just __pycache__: a
            # .DS_Store appearing changed the digest, expired a ledgered
            # exception with no content change, and -- since `audit` is a
            # dependency of `pixi run all` -- turned the build red until
            # someone re-ran --sha.
            if not child.is_file() or "__pycache__" in child.parts:
                continue
            if any(part.startswith(".") for part in child.relative_to(path).parts):
                continue
            h.update(child.relative_to(path).as_posix().encode())
            h.update(child.read_bytes())
        return h.hexdigest()
    return None


def asset_sha(root: Path, asset: str) -> str | None:
    """Hash of an asset, including a pairwise one.

    A pair hashes both halves in order, so editing either side expires the
    exception -- which is the whole point of keying the finding on the pair.
    """
    digests = []
    for part in asset.split(PAIR_SEP):
        digest = sha(root / part)
        if digest is None:
            return None
        digests.append(digest)
    if len(digests) == 1:
        return digests[0]
    return hashlib.sha256("".join(digests).encode()).hexdigest()


def load_ledger(path: Path = LEDGER) -> dict[str, str]:
    """`asset::P<n>` -> the asset's sha when the exception was granted.

    A missing field exits rather than warning: an entry without `asset_sha`
    would suppress its finding forever, which is exactly how
    friction-ledger.toml's `count_at_decision` rule fails when omitted.
    """
    if not path.exists():
        return {}
    out = {}
    for d in tomllib.loads(path.read_text(encoding="utf-8")).get("decision", []):
        missing = REQUIRED_LEDGER_FIELDS - {k for k, v in d.items() if str(v).strip()}
        if missing:
            raise SystemExit(
                f"{path.name}: entry for {d.get('asset', '?')} is missing "
                f"{sorted(missing)}. Every field is required; asset_sha most "
                "of all, since without it the exception never expires."
            )
        out[f"{d['asset']}::P{d['principle']}"] = d["asset_sha"]
    return out


def changed_assets(root: Path) -> set[str]:
    """Paths this branch has changed relative to the default branch.

    Empty on the default branch itself -- `main...main` is no diff -- which is
    what makes the re-grant grace below expire automatically once the work
    lands, with no branch name special-cased anywhere.
    """
    try:
        base = subprocess.run(
            ["git", "-C", str(root), "merge-base", default_branch(root), "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        # Diffed against the merge base rather than `base...HEAD`, so work that
        # is edited but not yet committed counts. The audit runs inside
        # `pixi run all`, which is what you run *before* committing, so a
        # commit-only view would have left the build red for exactly the window
        # the grace exists to cover.
        out = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", base],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        # Cannot tell what the branch touched, so grant no grace. Failing
        # closed keeps the gate honest when git is unavailable.
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def touched(asset: str, changed: set[str]) -> bool:
    """Whether `asset` -- a path, a directory, or a `+`-joined pair -- is in
    the changed set. Either half of a pair counts, matching how asset_sha
    expires a pairwise exception when either side moves."""
    for part in asset.split(PAIR_SEP):
        if any(c == part or c.startswith(f"{part}/") for c in changed):
            return True
    return False


def triage(
    findings: list[Finding],
    ledger: dict[str, str],
    root: Path = REPO_ROOT,
) -> tuple[list[Finding], list[Finding], list[Finding]]:
    """(live, awaiting re-grant, suppressed).

    `awaiting` is the middle state this repo previously had no name for: an
    exception that *was* granted, on an asset the current branch is editing.
    The old two-way split made it live, so `pixi run audit` -- and through it
    `pixi run all` -- went red the moment a ledgered asset was touched, and
    stayed red until the note was rewritten. That is what turned one re-grant
    per branch into one per commit, and the note into a running commentary on
    its own drafts.

    The grace is deliberately narrow. It needs a prior accepted exception for
    that exact key, so a genuinely new violation still fails; and it needs the
    asset to be changed relative to the default branch, so it evaporates when
    the work merges. On the default branch `changed` is empty and this
    collapses back to the old two-way split.
    """
    changed = changed_assets(root)
    live: list[Finding] = []
    awaiting: list[Finding] = []
    suppressed: list[Finding] = []
    for f in findings:
        recorded = ledger.get(f.key)
        current = asset_sha(root, f.asset)
        if recorded and current and recorded == current:
            suppressed.append(f)
        elif recorded and touched(f.asset, changed):
            awaiting.append(f)
        else:
            live.append(f)
    return live, awaiting, suppressed


MARKER = ".audit-owed"


def current_branch(root: Path) -> str:
    """The checked-out branch, or "" when git cannot say.

    The marker is scoped by branch because the obligation is: an audit is owed
    for the assets *this* branch changed. Without scoping, switching branches
    carries the warning across, and the obvious fix -- clearing it -- discards
    an obligation the other branch genuinely had.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def parse_marker(text: str) -> tuple[list[tuple[str, str]], dict[tuple[str, str], str]]:
    """Split marker lines into obligations and discharges.

    Three line shapes share the file, distinguished by field count:

    - `asset` -- an obligation written before branch scoping existed.
      Attributed to no branch, so it counts for every one: the safe reading
      of an obligation with no recorded owner is that it is still owed.
    - `branch<TAB>asset` -- an obligation, written by hooks/audit-owed.py.
    - `branch<TAB>asset<TAB>sha` -- a discharge: an audit was run against the
      asset while it hashed to `sha`.

    Obligations carry an empty branch when unscoped, which callers compare
    against their own branch permissively.
    """
    obligations: list[tuple[str, str]] = []
    discharges: dict[tuple[str, str], str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) == 1:
            obligations.append(("", fields[0]))
        elif len(fields) == 2:
            obligations.append((fields[0], fields[1]))
        else:
            # Extra fields are ignored rather than rejected, so a future field
            # cannot make an old reader treat a discharge as an obligation --
            # which would warn about an audit that had in fact been run.
            discharges[(fields[0], fields[1])] = fields[2]
    return obligations, discharges


def owed_assets(root: Path, branch: str, *, any_branch: bool) -> list[str]:
    """Assets `branch` owes an audit for, discharges subtracted.

    The obligation line survives `--clear-owed`; what the clear adds is a
    discharge, and the discharge answers the obligation only while the asset
    still hashes to what was audited. That is what makes clearing early
    self-correcting -- the stamp stands until the asset changes and the
    obligation surfaces again on its own, with no second write from the hook
    and no memory of whether an audit ever happened being thrown away.

    `any_branch` is how the default branch reports: merged work is now this
    branch's contents, so an obligation recorded against feat/x is the default
    branch's to discharge, and reporting only matching lines lost it silently.
    """
    marker = root / MARKER
    if not marker.is_file():
        return []
    obligations, discharges = parse_marker(marker.read_text(encoding="utf-8"))
    out = set()
    for recorded, asset in obligations:
        if recorded and not any_branch and recorded != branch:
            continue
        current = asset_sha(root, asset)
        # Any branch's discharge counts, because it is the hash that certifies
        # the audit, not who ran it -- and a discharge from elsewhere can only
        # match if that branch audited this exact content.
        # A missing asset stays owed here rather than lapsing: no discharge can
        # match a file that is gone, and deleting a skill is itself a config
        # change worth looking at. `--clear-owed` is what retires it, because
        # that is the step that cannot stamp a hash it has no file for.
        if current is not None and any(
            sha == current for (_, a), sha in discharges.items() if a == asset
        ):
            continue
        out.add(asset)
    return sorted(out)


def default_branch(root: Path) -> str:
    """Best-effort default-branch name. Mirrors preflight's resolver."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "symbolic-ref",
                "--short",
                "refs/remotes/origin/HEAD",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        if out.stdout.strip():
            return out.stdout.strip().split("/", 1)[-1]
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in ("main", "master"):
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{candidate}",
                ],
                capture_output=True,
                check=True,
                timeout=10,
            )
            return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return "main"


def live_branches(root: Path) -> set[str]:
    """Branch names git still knows about."""
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/heads",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.stdout.splitlines() if line.strip()}


def render_marker(
    obligations: list[tuple[str, str]], discharges: dict[tuple[str, str], str]
) -> list[str]:
    """The inverse of parse_marker. The only place a marker line is written,
    so the three shapes have one definition rather than one per caller."""
    lines = [f"{b}\t{a}" if b else a for b, a in sorted(set(obligations))]
    lines += [f"{b}\t{a}\t{sha}" for (b, a), sha in sorted(discharges.items())]
    return lines


def clear_owed(root: Path) -> str:
    """Discharge this branch's obligations, stamping what was audited.

    Clearing used to delete the lines, which threw away the only evidence an
    audit had happened: afterwards nothing could tell a branch that had never
    been audited from one audited and then edited again. The obligation now
    survives and a `branch<TAB>asset<TAB>sha` discharge is recorded beside it,
    so `owed_assets` can answer by hash -- the same expiry mechanism
    `audit-ledger.toml` uses, for the same reason.

    Reports honestly when git cannot name the branch: an earlier version kept
    every scoped line in that case and still printed "cleared", so the audit
    looked closed while preflight went on warning forever.

    Dead-branch lines are pruned because they are otherwise unreachable --
    clearing only ever touched the current branch, so every merged-and-deleted
    branch left a line nobody could remove.
    """
    marker = root / MARKER
    if not marker.is_file():
        return "no audit owed"
    obligations, discharges = parse_marker(marker.read_text(encoding="utf-8"))
    branch = current_branch(root)

    if not branch:
        # Only unscoped lines can be attributed to "here" with confidence, and
        # they carry no branch to stamp a discharge against, so they are
        # dropped rather than recorded.
        scoped = [(b, a) for b, a in obligations if b]
        dropped = len(obligations) - len(scoped)
        if not dropped:
            return (
                f"git could not name the current branch, so {len(scoped)} "
                "branch-scoped entry(s) were left alone. Nothing cleared."
            )
        _write_marker(marker, render_marker(scoped, discharges))
        return f"cleared {dropped} unscoped entry(s)"

    # On the default branch, merged work is now this branch's contents, so its
    # obligation is this branch's to discharge. But a branch that is still
    # alive and unmerged has not handed anything over -- dropping its line here
    # destroyed an obligation nobody had discharged. So the rule is the same on
    # either side: keep other branches that still exist, prune the rest.
    alive = live_branches(root)

    def survives(b: str) -> bool:
        # Unscoped entries have no branch to survive as, so they prune here.
        return bool(b) and (b == branch or b in alive)

    kept = [(b, a) for b, a in obligations if survives(b)]
    keep_di = {(b, a): sha for (b, a), sha in discharges.items() if survives(b)}
    pruned = (len(obligations) - len(kept)) + (len(discharges) - len(keep_di))

    mine = [a for b, a in kept if b == branch]
    for asset in mine:
        digest = asset_sha(root, asset)
        # An asset the branch deleted has nothing left to audit and no hash to
        # stamp, so the obligation lapses rather than nagging forever.
        if digest is None:
            kept.remove((branch, asset))
        else:
            keep_di[(branch, asset)] = digest

    # Counted from the obligations discharged, not from how many lines the file
    # lost. Clearing no longer removes lines, so line arithmetic reported
    # "cleared 0 entry(s)" for a branch whose single obligation had just been
    # recorded against its hash.
    others = sum(1 for b, _ in kept if b != branch)
    parts = [f"cleared {len(mine)} obligation(s), recorded as audited"]
    if pruned:
        parts.append(f"pruned {pruned} stale entry(s)")
    if others:
        parts.append(f"{others} left for other branches")
    _write_marker(marker, render_marker(kept, keep_di))
    return "; ".join(parts)


def _write_marker(marker: Path, kept: list[str]) -> None:
    """Write the surviving lines back, or remove an emptied marker."""
    if kept:
        marker.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        marker.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit this repo's assets against the five agent-asset principles."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output, for the config-audit skill",
    )
    parser.add_argument(
        "--no-ledger",
        action="store_true",
        help="report accepted exceptions as findings too",
    )
    parser.add_argument(
        "--owed",
        action="store_true",
        help="list the assets this branch owes an audit for",
    )
    parser.add_argument(
        "--clear-owed",
        action="store_true",
        help="record this branch's audit as done, stamping what was audited",
    )
    parser.add_argument(
        "--sha",
        metavar="ASSET",
        help="print an asset's content hash, for writing a ledger entry",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on warnings too, for an unsupervised run",
    )
    args = parser.parse_args(argv)

    if args.owed:
        # preflight asks through this rather than parsing the marker itself, so
        # the branch-scoped format has exactly one owner.
        branch = current_branch(REPO_ROOT)
        assets = owed_assets(
            REPO_ROOT, branch, any_branch=branch == default_branch(REPO_ROOT)
        )
        if args.json:
            print(json.dumps({"owed": assets}, indent=2))
        else:
            print("\n".join(assets) if assets else "no audit owed")
        return 0

    if args.clear_owed:
        # A warning nobody can clear is a warning everyone learns to ignore,
        # which is the failure the house rule about flaky gates names. The hook
        # that wrote the marker says to clear it in additionalContext -- i.e.
        # in exactly the context this design calls unreliable -- so clearing it
        # has to be a command the skill can name.
        print(clear_owed(REPO_ROOT))
        return 0

    if args.sha:
        digest = asset_sha(REPO_ROOT, args.sha)
        if digest is None:
            print(f"no such asset: {args.sha}", file=sys.stderr)
            return 2
        print(digest)
        return 0

    findings = audit()
    # Warnings never reach triage: they are not ledgerable (see Finding), and
    # asset_sha lookups for them would be work with nothing to decide.
    # --strict promotes them instead, which is how the nightly reflect loop
    # keeps the old hard behaviour: a soft band is a prompt to a human in the
    # room, and an unsupervised agent does not have one.
    failures, warnings = partition(findings, strict=args.strict)
    if args.no_ledger:
        live, awaiting, suppressed = failures, [], []
    else:
        live, awaiting, suppressed = triage(failures, load_ledger())
    if args.json:
        print(
            json.dumps(
                {
                    "findings": [asdict(f) for f in live],
                    "warnings": [asdict(f) for f in warnings],
                    "awaiting_regrant": [asdict(f) for f in awaiting],
                    "suppressed": [asdict(f) for f in suppressed],
                },
                indent=2,
            )
        )
    else:
        render(live)
        render_warnings(warnings)
        if awaiting:
            print(
                f"\n{len(awaiting)} ledgered exception(s) awaiting re-grant, on "
                "assets this branch changed:"
            )
            for f in awaiting:
                print(f"  P{f.principle}  {f.asset}")
            print(
                "Re-grant once, at branch end, against the asset's final state "
                "-- `pixi run audit --sha <asset>`. This is a failure on the "
                "default branch."
            )
        if suppressed:
            print(f"\n{len(suppressed)} ledgered exception(s); --no-ledger to show.")
    return 1 if live else 0


if __name__ == "__main__":
    sys.exit(main())
