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


def skill_texts(root: Path = REPO_ROOT) -> list[tuple[Path, str]]:
    """Every SKILL.md with its contents, read once.

    Three checks want the same text -- the trigger clause, the budgets, and
    the overlap scan -- and each walking skill_files itself meant the same
    file was read three times and the same two lines written three times.
    """
    return [(path, path.read_text()) for path in skill_files(root)]


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


def check_budgets(root: Path = REPO_ROOT) -> list[Finding]:
    """P3: spend context wisely."""
    out = []
    # Guarded like prose_files and pixi_tasks. Unguarded, `pixi run audit` on a
    # tree where CLAUDE.md was renamed tracebacks instead of reporting the P4
    # dangling references that rename produces -- the audit failing exactly
    # when it has something to say.
    claude_md = root / "CLAUDE.md"
    n = words(claude_md.read_text()) if claude_md.is_file() else 0
    if n > CLAUDE_MD_MAX_WORDS:
        out.append(
            Finding(
                3, "CLAUDE.md", f"{n} words, over the {CLAUDE_MD_MAX_WORDS} ceiling"
            )
        )
    for path, text in skill_texts(root):
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
        # rglob, not glob: the finding text and sha() both say "anywhere in the
        # skill directory", and references/<file>.md is the layout
        # superpowers:writing-skills prescribes -- reporting such a skill as
        # evidence-free is the punishing-compliance failure binding rule 2 names.
        texts = [p.read_text() for p in sorted(path.parent.rglob("*.md"))]
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
        root / "CLAUDE.md",
        root / "README.md",
        root / "audit-ledger.toml",
        root / "friction-ledger.toml",
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
        text = path.read_text()
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
            if not child.is_file() or "__pycache__" in child.parts:
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
    for d in tomllib.loads(path.read_text()).get("decision", []):
        missing = REQUIRED_LEDGER_FIELDS - {k for k, v in d.items() if str(v).strip()}
        if missing:
            raise SystemExit(
                f"{path.name}: entry for {d.get('asset', '?')} is missing "
                f"{sorted(missing)}. Every field is required; asset_sha most "
                "of all, since without it the exception never expires."
            )
        out[f"{d['asset']}::P{d['principle']}"] = d["asset_sha"]
    return out


def partition(
    findings: list[Finding], ledger: dict[str, str], root: Path = REPO_ROOT
) -> tuple[list[Finding], list[Finding]]:
    """(live, suppressed). An exception is granted to the asset as it stood."""
    live: list[Finding] = []
    suppressed: list[Finding] = []
    for f in findings:
        recorded = ledger.get(f.key)
        current = asset_sha(root, f.asset)
        if recorded and current and recorded == current:
            suppressed.append(f)
        else:
            live.append(f)
    return live, suppressed


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


def owed_assets(root: Path, branch: str) -> list[str]:
    """Assets recorded against `branch`. Tolerates unscoped legacy lines."""
    marker = root / MARKER
    if not marker.is_file():
        return []
    out = set()
    for line in marker.read_text().splitlines():
        if not line.strip():
            continue
        recorded, _, asset = line.partition("\t")
        if asset:
            if recorded == branch:
                out.add(asset)
        else:
            # Written before branch scoping existed. Counted for any branch,
            # because the safe reading of an obligation with no recorded owner
            # is that it is still owed. The hook does the same.
            out.add(recorded)
    return sorted(out)


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


def clear_owed(root: Path) -> str:
    """Drop this branch's entries plus any dead branch's. Returns a report.

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
    branch = current_branch(root)
    lines = [ln for ln in marker.read_text().splitlines() if ln.strip()]
    if not branch:
        # Only unscoped lines can be attributed to "here" with confidence.
        kept = [ln for ln in lines if "\t" in ln]
        if len(kept) == len(lines):
            return (
                f"git could not name the current branch, so {len(kept)} "
                "branch-scoped entry(s) were left alone. Nothing cleared."
            )
    else:
        alive = live_branches(root)
        kept = [
            ln
            for ln in lines
            if "\t" in ln
            and ln.partition("\t")[0] != branch
            and ln.partition("\t")[0] in alive
        ]
    dropped = len(lines) - len(kept)
    if kept:
        marker.write_text("\n".join(kept) + "\n")
        return f"cleared {dropped} entry(s); {len(kept)} left for other branches"
    marker.unlink()
    return f"cleared {marker.name} ({dropped} entry(s))"


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
        help="delete .audit-owed once the audit is done",
    )
    parser.add_argument(
        "--sha",
        metavar="ASSET",
        help="print an asset's content hash, for writing a ledger entry",
    )
    args = parser.parse_args(argv)

    if args.owed:
        # preflight asks through this rather than parsing the marker itself, so
        # the branch-scoped format has exactly one owner.
        assets = owed_assets(REPO_ROOT, current_branch(REPO_ROOT))
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
    live, suppressed = (
        (findings, []) if args.no_ledger else partition(findings, load_ledger())
    )
    if args.json:
        print(
            json.dumps(
                {
                    "findings": [asdict(f) for f in live],
                    "suppressed": [asdict(f) for f in suppressed],
                },
                indent=2,
            )
        )
    else:
        render(live)
        if suppressed:
            print(f"\n{len(suppressed)} ledgered exception(s); --no-ledger to show.")
    return 1 if live else 0


if __name__ == "__main__":
    sys.exit(main())
