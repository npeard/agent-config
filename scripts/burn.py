#!/usr/bin/env python
"""Report where a session's tokens actually go, from Claude Code transcripts.

Companion to friction.py, and deliberately the same shape: it reads the
JSONL transcripts on disk, so observation costs no model context, and it
always exits 0 because this is a report and not a gate.

It exists because this repo measured everything except the bill. friction.py
counts recurring *errors*; audit_assets.py and test_context_budget.py bound
*static* always-loaded prose to the word. Neither can see the dominant cost,
which is dynamic. Over the first month measured this way, cache reads --
the conversation being re-sent every turn -- were 61% of orchestrator spend
and 47% of the total once subagents are priced, and the mean cost of a turn
rose 2.7x between a session's first decile and its last. A 700-turn session
costs roughly 3x per turn what a 100-turn session does, and nothing in the
repo would have shown that.

Two numbers here are regression signals for changes already made, which is
the point of having an instrument rather than an anecdote:

  dispatches_missing_model  hooks/agent-model.py denies these, so it should
                            trend to zero. Non-zero means the hook is not
                            firing (it has been unregistered, or the agent
                            type is one it deliberately skips).
  review rounds per session The step 6 loop was scoped to the fix diff and
                            to correctness findings; if rounds per session
                            do not fall from the 3-5 observed before that
                            change, the change did not work.

Usage:
    python scripts/burn.py [--json] [--project NAME] [--since DAYS]
                           [--all-time] [--sessions]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Matches friction.py: only the recent past is actionable, and a lifetime
# window would average away the trend this tool exists to show.
DEFAULT_WINDOW_DAYS = 30

# Base rates in USD per million tokens, as (input, output), keyed by model
# family.
#
# VERIFIED 2026-09-03 against the bundled claude-api skill's model table.
# This table is the one thing here that can go stale silently and still
# produce confident output, so render() prints the rates it used next to
# every total -- a wrong number should show up in the report rather than
# hide inside the arithmetic. Re-verify before trusting a dollar figure.
PRICING = {
    "opus": (5.00, 25.00),
    "sonnet": (2.00, 10.00),
    "haiku": (1.00, 5.00),
    "fable": (10.00, 50.00),
}
# Cache multipliers against the family's input rate. A 1h write costs more
# than a 5m write, and the usage record distinguishes them, so they are
# priced separately rather than averaged -- this config writes 1h entries,
# which is the difference between a $571 and a $357 line item on one month.
CACHE_WRITE_1H = 2.00
CACHE_WRITE_5M = 1.25
CACHE_READ = 0.10

# Unknown models price as opus. Guessing high is the safe direction for a
# cost report: it cannot lull you into thinking a session was cheap, and a
# new model id showing up here is visible in the model mix anyway.
DEFAULT_FAMILY = "opus"

# Read-only shell work is the delegable category -- reading to understand,
# as opposed to acting. It is the expensive kind to run in the orchestrator,
# because the output then sits in context and is re-read at cache-read rates
# on every later turn, where the same sweep in a subagent returns a summary
# and discards the rest.
#
# A regex heuristic, and knowingly approximate: promotion-check.py does this
# properly with shlex because it must never misreport a *write*, but here a
# few percent of misclassification cannot hurt anyone -- the number is a
# trend line, not a gate. Ordered write-first, so `cat x > y` is a write.
WRITE_ISH = re.compile(
    r"(^|\s)(rm|mv|cp|mkdir|touch|chmod|install|tee|dd)\s|"
    r"[^<>&|]>[>|]?\s*\S|sed\s+-[a-z]*i|--in-place|"
    r"(^|\s)git\s+(commit|merge|add|push|checkout|switch|stash|rebase|reset|tag)\b"
)
READ_ISH = re.compile(
    r"(^|\s|\|)(cat|sed|head|tail|less|grep|rg|find|ls|wc|awk|tree|du|file|stat|"
    r"diff|nl|sort|uniq|cut|jq)(\s|$)"
)
# Running the suite is orchestration, not comprehension: the orchestrator
# needs the pass/fail itself, so these are excluded from the delegable count
# even though they are read-only in the filesystem sense.
RUNNER = re.compile(
    r"(^|\s)(pixi\s+run|pytest|ruff|mypy|codespell|pre-commit|npm|make|cargo|"
    r"latexmk|pdflatex|cmake|tox|nox)\b"
)

# Skills whose invocation is a review round. Counted per session as the
# convergence signal for the step 6 loop.
REVIEW_SKILLS = frozenset(
    {
        "code-review",
        "code-review:code-review",
        "simplify",
        "standards-and-spec-review",
        "config-audit",
    }
)

# Agent types that carry no model of their own, so omitting `model` inherits
# the parent's. Kept in step with hooks/agent-model.py's CATCH_ALL: a type
# missing here would be reported as a deliberate choice when it was an
# omission, which is the opposite of what the signal is for.
CATCH_ALL = frozenset({"", "general-purpose", "claude", "default"})


# Everything this report prints that it did not author itself -- project
# directory names, and the `model` string off an Agent dispatch -- comes out
# of a transcript, and a transcript can contain anything a model or a tool
# result put there. friction.py has the same boundary and answers it by
# quoting an excerpt as a JSON string literal; here the untrusted values are
# short identifiers rather than prose, so they are filtered to an identifier
# charset instead. That is the stronger answer for this shape: a name that
# cannot contain a newline or an escape cannot forge a row, restate the
# totals, or smuggle an instruction into a report a model will read.
SAFE_NAME = re.compile(r"[^A-Za-z0-9._:@/\[\]-]")


def safe(value: str, limit: int = 40) -> str:
    """A transcript-derived identifier, reduced to something printable."""
    cleaned = SAFE_NAME.sub("?", str(value))[:limit]
    return cleaned or "(blank)"


def is_delegable_read(name: str, tool_input: dict) -> bool:
    """Whether this call is reading-to-understand, the delegable category.

    The boundary the delegation question turns on: the orchestrator decides
    and acts, subagents read. Running the suite is *not* delegable even
    though it only reads the filesystem -- the orchestrator needs the
    pass/fail itself. Acting (writes, commits, edits) is not delegable
    because it is the orchestration.
    """
    if name != "Bash":
        return False
    command = " ".join(str(tool_input.get("command") or "").split())
    if not command or RUNNER.search(command) or WRITE_ISH.search(command):
        return False
    return bool(READ_ISH.search(command))


def result_size(content) -> int:
    """Characters a tool result contributes to context.

    Both shapes appear in transcripts: a list of text blocks, or a bare
    string. Sizing only one of them undercounted the whole measurement.
    """
    if isinstance(content, list):
        return sum(
            len(block.get("text") or "") for block in content if isinstance(block, dict)
        )
    return len(str(content or ""))


def family(model: str | None) -> str:
    name = (model or "").lower()
    for key in PRICING:
        if key in name:
            return key
    return DEFAULT_FAMILY


def numeric(value) -> float:
    """A token count from a usage record, or 0 for anything unusable.

    Coerced rather than trusted. A single record carrying a non-numeric
    count used to raise out of cost() and kill the whole sweep, which breaks
    this script's own promise to be a report rather than a gate -- and a
    report that dies on one bad record in thirty days of transcripts is a
    report nobody runs. friction.py tolerates a malformed *line* for the
    same reason; this is the same rule one level further in.
    """
    if isinstance(value, bool):
        # bool is an int subclass, and True would silently price as 1 token.
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def cost(usage: dict, model: str | None) -> float:
    """Dollars for one assistant turn."""
    rate_in, rate_out = PRICING[family(model)]
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        write_1h = numeric(creation.get("ephemeral_1h_input_tokens"))
        write_5m = numeric(creation.get("ephemeral_5m_input_tokens"))
    else:
        # Older records carry only the total. Charging it at the 1h rate
        # follows the same guess-high rule as DEFAULT_FAMILY.
        write_1h = numeric(usage.get("cache_creation_input_tokens"))
        write_5m = 0.0
    return (
        numeric(usage.get("input_tokens")) * rate_in
        + write_1h * rate_in * CACHE_WRITE_1H
        + write_5m * rate_in * CACHE_WRITE_5M
        + numeric(usage.get("cache_read_input_tokens")) * rate_in * CACHE_READ
        + numeric(usage.get("output_tokens")) * rate_out
    ) / 1e6


def cutoff_date(days: int | None) -> str:
    """Earliest date to count, as YYYY-MM-DD, or "" for all time.

    Day granularity, compared against a timestamp's first ten characters --
    the same trick friction.py uses to sidestep "...Z" versus "+00:00".
    """
    if days is None:
        return ""
    return (datetime.now(UTC) - timedelta(days=days)).date().isoformat()


def transcript_files(project: str | None) -> list[tuple[Path, bool]]:
    """[(path, is_subagent)] for every transcript in scope.

    Subagent transcripts live at <project>/<session-id>/subagents/agent-*.jsonl
    and are included, unlike in friction.py, which is looking for errors the
    orchestrator saw. Here they are the whole question: delegation cannot be
    compared against doing the work inline if the delegated half is invisible,
    and leaving them out makes every subagent look free.
    """
    if not PROJECTS_DIR.is_dir():
        return []
    root = PROJECTS_DIR / project if project else PROJECTS_DIR
    if project and not root.is_dir():
        return []
    depth = "" if project else "*/"
    top = [(p, False) for p in sorted(root.glob(f"{depth}*.jsonl"))]
    sub = [(p, True) for p in sorted(root.glob(f"{depth}*/subagents/*.jsonl"))]
    return top + sub


def session_of(path: Path, is_subagent: bool) -> str:
    """The orchestrator session a transcript belongs to.

    A subagent file sits two directories below its session, so its cost is
    attributed to the session that spawned it rather than to a session of its
    own -- otherwise the per-session totals would split one piece of work in
    two and the delegation ratio would have no denominator.
    """
    return path.parent.parent.name if is_subagent else path.stem


def project_of(path: Path, is_subagent: bool) -> str:
    return path.parent.parent.parent.name if is_subagent else path.parent.name


class Burn:
    """Everything measured about one orchestrator session."""

    def __init__(self, project: str) -> None:
        self.project = project
        self.first = ""
        self.last = ""
        self.turns = 0
        self.sub_turns = 0
        self.cost = 0.0
        self.sub_cost = 0.0
        self.components = collections.Counter()  # token totals by kind
        self.models = collections.Counter()
        self.sub_models = collections.Counter()
        self.dispatch_models = collections.Counter()
        self.missing_model = 0
        self.review_rounds = 0
        self.read_only_bash = 0
        self.acting_bash = 0
        self.dispatches = 0
        self.max_context = 0
        self.turn_costs: list[float] = []
        # Chars of tool output landing in orchestrator context, split by
        # whether the call that produced it was delegable. This is the
        # measurement that justifies delegating at all: read-only shell
        # output is 41% of everything accumulating in context, and context
        # is re-read at cache-read rates on every later turn.
        self.result_chars = 0
        self.read_only_chars = 0
        # One subagent transcript is one dispatch, so its own total is what
        # a dispatch costs -- the number the delegate-or-inline decision
        # has to be weighed against.
        self.dispatch_costs: list[tuple[float, str]] = []

    def record_turn(self, usage: dict, model: str | None, is_subagent: bool) -> None:
        spend = cost(usage, model)
        if is_subagent:
            self.sub_turns += 1
            self.sub_cost += spend
            self.sub_models[model or "?"] += 1
            return
        self.turns += 1
        self.cost += spend
        self.models[model or "?"] += 1
        self.turn_costs.append(spend)
        read = numeric(usage.get("cache_read_input_tokens"))
        self.max_context = max(self.max_context, read)
        self.components["cache_read"] += read
        self.components["cache_write"] += numeric(
            usage.get("cache_creation_input_tokens")
        )
        self.components["input"] += numeric(usage.get("input_tokens"))
        self.components["output"] += numeric(usage.get("output_tokens"))
        details = usage.get("output_tokens_details")
        if isinstance(details, dict):
            self.components["thinking"] += numeric(details.get("thinking_tokens"))

    def record_tool(self, name: str, tool_input: dict) -> None:
        if name == "Bash":
            # One predicate, used here and to size the result it produces --
            # two copies would drift and the share would stop matching the
            # count it is a share of.
            if is_delegable_read(name, tool_input):
                self.read_only_bash += 1
            else:
                self.acting_bash += 1
        elif name == "Agent":
            self.dispatches += 1
            model = tool_input.get("model")
            named = model.strip().lower() if isinstance(model, str) else ""
            self.dispatch_models[named or "no-model"] += 1
            subagent_type = tool_input.get("subagent_type")
            kind = (
                subagent_type.strip().lower() if isinstance(subagent_type, str) else ""
            )
            if not named and kind in CATCH_ALL:
                self.missing_model += 1
        elif name == "Skill" and str(tool_input.get("skill")) in REVIEW_SKILLS:
            self.review_rounds += 1

    def record_result(self, chars: int, delegable: bool) -> None:
        self.result_chars += chars
        if delegable:
            self.read_only_chars += chars

    def record_dispatch_cost(self, spend: float, model: str | None) -> None:
        self.dispatch_costs.append((spend, family(model)))

    def see(self, timestamp: str) -> None:
        if not timestamp:
            return
        self.first = min(self.first, timestamp) if self.first else timestamp
        self.last = max(self.last, timestamp)

    @property
    def total(self) -> float:
        return self.cost + self.sub_cost


def collect(files: list[tuple[Path, bool]], since: str = "") -> dict[str, Burn]:
    sessions: dict[str, Burn] = {}
    for path, is_subagent in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        key = session_of(path, is_subagent)
        # tool_use id -> whether that call was delegable reading. A result
        # arrives in a later record than the call that caused it, so sizing
        # it by origin needs this join; without it every result looks alike
        # and the delegable share cannot be separated out.
        delegable: dict[str, bool] = {}
        file_cost = 0.0
        file_model = None
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("type") == "user" and not is_subagent:
                message = record.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                for block in content or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_result":
                        continue
                    origin = block.get("tool_use_id")
                    if origin not in delegable:
                        continue
                    burn = sessions.get(key)
                    if burn is not None:
                        burn.record_result(
                            result_size(block.get("content")), delegable[origin]
                        )
                continue
            if record.get("type") != "assistant":
                continue
            timestamp = record.get("timestamp") or ""
            # An undated record is counted rather than dropped: "" sorts
            # before every date, so testing it against the window would
            # silently discard evidence. friction.py guards the same way.
            if since and timestamp and timestamp[:10] < since:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            burn = sessions.setdefault(key, Burn(project_of(path, is_subagent)))
            burn.see(timestamp)
            usage = message.get("usage")
            if isinstance(usage, dict):
                burn.record_turn(usage, message.get("model"), is_subagent)
                if is_subagent:
                    file_cost += cost(usage, message.get("model"))
                    file_model = message.get("model") or file_model
            if is_subagent:
                # Only the orchestrator's own tool use bears on the
                # delegation question; counting a subagent's greps as
                # undelegated work would penalise delegating.
                continue
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_input = block.get("input")
                    tool_input = tool_input if isinstance(tool_input, dict) else {}
                    name = block.get("name") or ""
                    burn.record_tool(name, tool_input)
                    delegable[block.get("id")] = is_delegable_read(name, tool_input)
        if is_subagent and file_cost:
            parent = sessions.get(key)
            if parent is not None:
                parent.record_dispatch_cost(file_cost, file_model)
    return sessions


def deciles(sessions: dict[str, Burn], buckets: int = 10) -> list[float]:
    """Mean orchestrator cost per turn by position through a session.

    The context tax made visible: turn 700 costs more than turn 7 for the
    same work, because it re-reads everything before it. Short sessions are
    excluded -- a 10-turn session has no meaningful decile structure and
    flattens the curve it is being averaged into.
    """
    totals = [0.0] * buckets
    counts = [0] * buckets
    for burn in sessions.values():
        n = len(burn.turn_costs)
        if n < 50:
            continue
        for index, spend in enumerate(burn.turn_costs):
            slot = min(buckets - 1, index * buckets // n)
            totals[slot] += spend
            counts[slot] += 1
    return [t / c if c else 0.0 for t, c in zip(totals, counts, strict=True)]


def tokens(n: int) -> str:
    for unit, size in (("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


def summary(sessions: dict[str, Burn]) -> dict:
    """Machine-readable, for tracking the two regression signals over time."""
    rounds = [b.review_rounds for b in sessions.values() if b.review_rounds]
    result_chars = sum(b.result_chars for b in sessions.values())
    read_only_chars = sum(b.read_only_chars for b in sessions.values())
    share = read_only_chars / result_chars if result_chars else 0.0
    return {
        "sessions": len(sessions),
        "cost_total": round(sum(b.total for b in sessions.values()), 2),
        "cost_orchestrator": round(sum(b.cost for b in sessions.values()), 2),
        "cost_subagents": round(sum(b.sub_cost for b in sessions.values()), 2),
        "dispatches": sum(b.dispatches for b in sessions.values()),
        "dispatches_missing_model": sum(b.missing_model for b in sessions.values()),
        "read_only_bash": sum(b.read_only_bash for b in sessions.values()),
        "acting_bash": sum(b.acting_bash for b in sessions.values()),
        "read_only_context_share": round(share, 3),
        "review_rounds_max": max(rounds, default=0),
        "review_rounds_mean": round(sum(rounds) / len(rounds), 1) if rounds else 0.0,
    }


def render(sessions: dict[str, Burn], since: str, show_sessions: bool) -> None:
    window = f"since {since}" if since else "all time"
    if not sessions:
        print(f"No transcripts with usage data ({window}).")
        return
    ordered = sorted(sessions.values(), key=lambda b: b.first)
    total = sum(b.total for b in ordered)
    orchestrator = sum(b.cost for b in ordered)
    subagents = sum(b.sub_cost for b in ordered)

    print(f"window: {window}   sessions: {len(ordered)}")
    rates = ", ".join(
        f"{name} ${i:g}/${o:g}" for name, (i, o) in sorted(PRICING.items())
    )
    # Printed every run on purpose: a stale PRICING table is the one way this
    # report can be confidently wrong, so the assumption travels with the
    # number rather than living only in a comment.
    print(f"rates per Mtok (in/out), VERIFIED 2026-09-03: {rates}")
    print(
        f"cache: write-1h {CACHE_WRITE_1H}x in, write-5m {CACHE_WRITE_5M}x, read {CACHE_READ}x\n"
    )

    if show_sessions:
        print(
            f"{'date':10} {'project':24} {'turns':>5} {'sub':>4} "
            f"{'maxctx':>7} {'orch$':>7} {'sub$':>6} {'rev':>3} {'ro/act':>8}"
        )
        for b in ordered:
            print(
                f"{safe(b.first[:10], 10):10} {safe(b.project, 200)[-24:]:24} {b.turns:5} {b.sub_turns:4} "
                f"{tokens(b.max_context):>7} {b.cost:7.2f} {b.sub_cost:6.2f} "
                f"{b.review_rounds:3} {b.read_only_bash:4}/{b.acting_bash:<4}"
            )
        print()

    print(
        f"cost ${total:.2f}  =  orchestrator ${orchestrator:.2f}  +  "
        f"subagents ${subagents:.2f} ({100 * subagents / total if total else 0:.0f}%)"
    )

    components = collections.Counter()
    for b in ordered:
        components.update(b.components)
    print("\norchestrator tokens by kind:")
    for kind in ("cache_read", "cache_write", "output", "input", "thinking"):
        n = components[kind]
        note = " (subset of output)" if kind == "thinking" else ""
        print(f"  {kind:12} {tokens(n):>8}{note}")

    curve = deciles(sessions)
    if any(curve):
        print("\ncontext tax -- mean orchestrator $/turn by session decile:")
        first, last = curve[0], curve[-1]
        bar = "  ".join(f"{c:.3f}" for c in curve)
        print(f"  {bar}")
        if first:
            print(f"  last decile costs {last / first:.1f}x the first per turn")

    print("\ndelegation:")
    read_only = sum(b.read_only_bash for b in ordered)
    acting = sum(b.acting_bash for b in ordered)
    dispatches = sum(b.dispatches for b in ordered)
    print(f"  orchestrator bash: {read_only} read-only, {acting} acting")
    print(f"  agent dispatches:  {dispatches}")
    if dispatches:
        print(f"  read-only bash per dispatch: {read_only / dispatches:.1f}")
    mix = collections.Counter()
    for b in ordered:
        mix.update(b.dispatch_models)
    if mix:
        print(
            "  dispatch model mix: "
            + ", ".join(f"{safe(name, 16)} {n}" for name, n in mix.most_common())
        )

    dispatch_costs = [c for b in ordered for c in b.dispatch_costs]
    result_chars = sum(b.result_chars for b in ordered)
    read_only_chars = sum(b.read_only_chars for b in ordered)
    if result_chars:
        print(
            f"  read-only shell output is {100 * read_only_chars / result_chars:.0f}%"
            " of tool output entering context"
        )
    if dispatch_costs and read_only_chars and read_only:
        mean_chars = read_only_chars / read_only
        # ~4 chars per token is the standard rough conversion; this is a
        # break-even ratio, so a 10-20% error in it does not change which
        # side of the line a model tier falls on.
        kept = mean_chars / 4 * CACHE_READ * PRICING[DEFAULT_FAMILY][0] / 1e6
        by_family = collections.defaultdict(list)
        for spend, fam in dispatch_costs:
            by_family[fam].append(spend)
        print(
            f"\n  one read-only result averages {mean_chars:.0f} chars; keeping it"
            " costs roughly"
        )
        for remaining in (100, 300):
            print(f"    ${kept * remaining:.3f} over {remaining} further turns")
        print("\n  median cost of one dispatch, and the read-only calls it must")
        print("  replace to pay for itself (at 100 / 300 turns remaining):")
        for fam in sorted(by_family, key=lambda f: statistics.median(by_family[f])):
            median = statistics.median(by_family[fam])
            print(
                f"    {fam:7} ${median:6.3f}  "
                f"{median / (kept * 100):5.0f} / {median / (kept * 300):.0f} calls"
            )
        print(
            "  => delegate reading to haiku or sonnet, and early; an opus\n"
            "     subagent has to replace a sweep no search actually is."
        )

    missing = sum(b.missing_model for b in ordered)
    print("\nregression signals:")
    print(
        f"  dispatches_missing_model: {missing}  (hooks/agent-model.py denies "
        "these; expected 0)"
    )
    rounds = [b.review_rounds for b in ordered if b.review_rounds]
    if rounds:
        print(
            f"  review rounds per session: mean {sum(rounds) / len(rounds):.1f}, "
            f"max {max(rounds)}  (3-5 before step 6 was scoped)"
        )
    else:
        print("  review rounds per session: none recorded")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    parser.add_argument("--project", help="limit to one project directory")
    parser.add_argument(
        "--sessions", action="store_true", help="per-session breakdown table"
    )
    parser.add_argument(
        "--since",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        metavar="DAYS",
        help=f"only count the last DAYS days (default {DEFAULT_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--all-time", action="store_true", help="ignore the recency window"
    )
    args = parser.parse_args(argv)

    since = cutoff_date(None if args.all_time else args.since)
    sessions = collect(transcript_files(args.project), since)
    if args.json:
        print(json.dumps(summary(sessions), indent=2))
    else:
        render(sessions, since, args.sessions)
    # Always 0: a report is not a gate. friction.py makes the same promise.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
