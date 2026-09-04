#!/usr/bin/env python3
# claude-hook: PreToolUse Agent
"""Require an explicit `model` on catch-all Agent dispatches.

The master CLAUDE.md already asks for "the cheapest model that holds
accuracy", but the harness default fights the rule: omitting `model` makes a
subagent inherit the parent's model, and this config runs Opus. So the rule
can only ever be broken in the expensive direction, and forgetting the
parameter costs the most a dispatch can cost.

Measured over 30 days of transcripts: 19 of 163 dispatches omitted `model`.
One session omitted it on all 10 of its dispatches and was the second most
expensive of 34; six of those ten were Opus subagents running repeated-trial
baseline measurement, which is Haiku work. Nobody chose Opus there; the
field was simply absent.

This denies rather than advises, which is the point. An advisory is a second
request to behave, and the first one is already in CLAUDE.md being ignored.
Denying converts a silent default into a named choice at the cost of one
round trip -- and "opus" remains a perfectly good answer, it just has to be
typed. Tier 1 on the reflect ladder for exactly this reason: a hook does not
gate on what survived compaction.
"""

import json
import sys

# The catch-all agent types, which carry no model of their own -- for these,
# an absent `model` resolves to the parent's. Every other type is left alone:
# a named specialist may define its own model in its frontmatter (so demanding
# an override would override a deliberate choice), and `fork` ignores the
# parameter entirely, so requiring it would be incoherent. Being narrow here
# is deliberate: a new specialist agent should not start failing because this
# hook has never heard of it.
CATCH_ALL = frozenset({"", "general-purpose", "claude", "default"})

# The tier-to-work mapping below also appears in workflow-orchestration's
# "Model tier" paragraph and, as measured break-even ratios, in burn.py's
# report. That is three statements of one idea, so it is worth saying why
# they are not consolidated: this message has to be self-contained. It
# arrives at dispatch time, when the skill may never have been loaded, and
# pointing at a skill instead would cost the round trip the deny already
# costs. The skill says which tier suits which work; burn.py says what each
# tier costs; this says a tier must be named at all.
REASON = (
    "Pass an explicit `model` to the Agent tool. Omitting it inherits this "
    "session's model (Opus), so the default is the most expensive option and "
    "CLAUDE.md's 'cheapest model that holds accuracy' can only be missed "
    "upward. Choose: `haiku` for mechanical work (scoped fixes, deletions, "
    "re-reviewing one diff, search sweeps), `sonnet` for implementation and "
    "review that needs judgement, `opus` for design-sensitive work. `opus` "
    "is a valid answer -- it just has to be named rather than defaulted to."
)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        # A hook that tracebacks is noisier than one that declines; the other
        # hooks in this directory guard the identical call.
        return
    if not isinstance(data, dict):
        # json.load only raises for *malformed* JSON, so a valid non-object
        # body decodes fine and then has no .get.
        return
    # The settings.json matcher already narrows this, but a hook that depends
    # on a file it cannot read for correctness misfires the day that file is
    # edited by hand -- notify.py guards the same way.
    if data.get("tool_name") != "Agent":
        return
    # A strict isinstance test rather than `or {}`. promotion-check.py can
    # use `or {}` because PostToolUse legitimately sends `tool_response: null`
    # for a rejected call; here an absent or non-dict tool_input is a
    # malformed dispatch, and coercing it to {} made this hook deny for
    # "no model" when the real problem was that there was no dispatch to
    # read -- the wrong reason, reported confidently.
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return

    # Whitespace counts as absent: `model: " "` would otherwise satisfy the
    # check while still resolving to the inherited model.
    model = tool_input.get("model")
    if isinstance(model, str) and model.strip():
        return

    subagent_type = tool_input.get("subagent_type")
    # A non-string subagent_type is a malformed call the harness will reject
    # on its own; guessing at it here would deny for the wrong reason.
    if subagent_type is not None and not isinstance(subagent_type, str):
        return
    if (subagent_type or "").strip().lower() not in CATCH_ALL:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": REASON,
                }
            }
        )
    )


if __name__ == "__main__":
    main()
