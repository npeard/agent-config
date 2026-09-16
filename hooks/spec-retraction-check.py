#!/usr/bin/env python3
# claude-hook: PreToolUse Write|Edit
"""Catch retraction-shaped language in a spec, at the moment the spec is written.

`AGENTS.md` and the `writing-orchestration` skill both already say "a
correction replaces the claim it corrects". The rule is clearly written, it is
in two places, and it was still violated twice in one branch -- because it
binds the *spec stage*, and nothing reviews a spec.

The failure mode is worth stating exactly, because it is not an agent ignoring
a rule. A spec said "Specific claims to retract or rewrite" and listed nine
claims to retract. Every downstream agent complied correctly and produced a
report with retraction subsections in it. Three separate standards-and-spec
reviews passed it, because each checked the diff against the spec, and the
spec was the defect. The skill even names this exact scenario as its worked
example. Restating the rule a third time would change nothing; the gap is that
the orchestrator writes the brief with no check between intention and handoff.

So this fires on a *spec* file, not a prose file (hooks/prose-writing.py owns
that), and not on the report -- by the time the report is written the brief has
already caused the defect.

PreToolUse for the same reason prose-writing.py chose it: before the handoff is
the only moment the brief can still be reworded. Afterwards a subagent is
already following it.

Advisory, never blocking. "Retract" is a legitimate word in a spec that is
*recording* an earlier finding ("the retracted figures were 2x lower"), and a
hook cannot tell that from an instruction to put a retraction in a
deliverable. Blocking on an ambiguous signal trains its reader to work around
it; naming the rule and letting the author judge does not.

Fires once per session per project, matching prose-writing.py: a spec is
edited repeatedly while being drafted, and the same advisory on every edit
costs context and buys less each time.

Path handling follows hooks/promotion-check.py and hooks/prose-writing.py:
realpath and lowercase before comparing, because this repo's files are
reachable through ~/.claude symlinks and a raw prefix test silently never
matches through one.

Depends on nothing outside the standard library, deliberately -- the
interpreter that runs a hook is named in ~/.claude/settings.json, outside this
repo and outside its checks.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path


def forward_slashed(path) -> str:
    """One separator convention everywhere, so two paths are comparable."""
    return str(path).replace(os.sep, "/")


def resolve(path: str) -> str:
    """Resolved and forward-slashed, with real case preserved."""
    return forward_slashed(os.path.realpath(os.path.normpath(path)))


def canonical(path: str) -> str:
    """Resolved and lowercased: the form every pattern test uses."""
    return resolve(path).lower()


# Where specs live. `docs/superpowers/` is the writing-plans convention; the
# other two catch projects that keep them elsewhere. Matched as a path
# fragment rather than a prefix so it works from any checkout.
SPEC_DIR_FRAGMENTS = ("/docs/superpowers/", "/docs/specs/", "/specs/")

# A filename ending this way is a spec wherever it sits, which covers the
# orchestrator that writes one into a scratch directory.
SPEC_STEM_SUFFIXES = ("-spec", "_spec", "-plan", "_plan")

# Instruction-shaped retraction language. The distinction this tries to draw
# is between *recording* that something was retracted (fine, and common in a
# spec's background section) and *instructing* a deliverable to carry a
# retraction (the defect).
#
# So the patterns are deliberately verb-and-object shaped: "claims to
# retract", "retract the X claim", "add a retraction". A bare "retracted"
# appearing in a past-tense background note does not match, which is the
# false positive that would otherwise make this hook noise.
PATTERNS = (
    re.compile(r"\bclaims?\s+to\s+retract\b", re.IGNORECASE),
    re.compile(r"\bretract\s+(?:the|this|that|its)\b", re.IGNORECASE),
    re.compile(r"\badd\s+(?:a|the)\s+retraction\b", re.IGNORECASE),
    re.compile(
        r"\bretraction\s+(?:section|subsection|slide|paragraph)\b", re.IGNORECASE
    ),
    re.compile(
        r"\bwhat\s+the\s+(?:earlier|previous|old)\s+draft\s+claimed\b", re.IGNORECASE
    ),
    re.compile(r"\bwhat\s+replaces\s+it\b", re.IGNORECASE),
)

ADVISORY = """\
This file looks like a spec, and it contains retraction-shaped instructions \
({matches}).

AGENTS.md: "A correction replaces the claim it corrects -- no retraction kept \
in a deliverable. This binds the spec stage, where it starts."

The failure this prevents is not an agent ignoring the rule. A brief that says \
"retract claim X" is followed correctly, and the result is a deliverable with a \
retraction section in it -- read by someone who never held claim X and does not \
care what an earlier draft said. Diff-versus-spec review cannot catch it, \
because the spec is the defect.

Write the brief as *state Y* rather than *retract X and replace it with Y*. The \
superseded claim belongs in the commit message and the chat, where the people \
who held it will see it. If this spec is only recording an earlier finding as \
background rather than instructing a deliverable, this is a false positive -- \
carry on.

See the writing-orchestration skill, which carries the orchestrator's half of \
this rule, and CODING_STANDARDS.md rule 11 for the author-facing half.\
"""


def is_spec(path: str) -> bool:
    """Whether this path is a spec or plan document."""
    lowered = canonical(path)
    if not lowered.endswith(".md"):
        return False
    if any(fragment in lowered for fragment in SPEC_DIR_FRAGMENTS):
        return True
    stem = Path(lowered).stem
    return stem.endswith(SPEC_STEM_SUFFIXES)


def written_text(payload: dict) -> str:
    """The text this tool call would put in the file.

    Write carries the whole file; Edit carries only the replacement, which is
    the right thing to scan -- a spec whose offending line is untouched by this
    edit should not re-fire on every later edit.
    """
    tool_input = payload.get("tool_input") or {}
    parts = [
        tool_input.get("content") or "",
        tool_input.get("new_string") or "",
    ]
    for edit in tool_input.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string") or "")
    return "\n".join(parts)


def once_per_session(session_id: str, project: str) -> bool:
    """True the first time this session asks for this project.

    Same mechanism as prose-writing.py: a marker file under the system temp
    directory, keyed by session and project. Temp rather than the project tree
    so a repo never acquires hook bookkeeping as an untracked file.
    """
    key = hashlib.sha256(f"{session_id}\x00{project}".encode()).hexdigest()[:32]
    marker = Path(tempfile.gettempdir()) / f"agent-config-spec-retraction-{key}"
    if marker.exists():
        return False
    try:
        marker.write_text("", encoding="utf-8")
    except OSError:
        # An unwritable temp dir should not silence the advisory; firing more
        # than once is strictly better than never firing.
        return True
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path or not is_spec(path):
        return 0

    text = written_text(payload)
    if not text:
        return 0

    hits = sorted({m.group(0).lower() for p in PATTERNS for m in p.finditer(text)})
    if not hits:
        return 0

    session = str(payload.get("session_id") or "")
    project = canonical(payload.get("cwd") or os.getcwd())
    if not once_per_session(session, project):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": ADVISORY.format(matches=", ".join(hits)),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
