#!/usr/bin/env python3
# claude-hook: PostToolUse Write|Edit
"""Hand the agent the plain-text math its edit just wrote.

Fires after a Write or Edit of a .typ, .tex or matplotlib .py file and runs
scripts/plain_math.py on it. A figure label "mean |<kappa_b>|" or a prose
"3pi/2" compiles, so the agent never hears about it until a reader does.

Only findings on the lines the tool wrote block; the rest of the file's count
is mentioned, not listed. A block over legacy text the agent never touched is
one it cannot clear in scope, and a gate that cannot be cleared is trained
away -- the same split hooks/prose-feedback.py makes. Clearing a block means
typesetting the token as math or adding a reasoned `math-ok:` comment.

Never blocks on failure: a file that does not parse mid-edit, or a checker
that raises, yields no output, because a broken feedback hook must not stop
edits. The checker is imported rather than spawned, so there is no
subprocess to time out.

Stdlib only: the interpreter that runs a hook is named in
~/.claude/settings.json, outside this repo and its checks.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(os.path.realpath(__file__)).parent.parent
SCRIPT = REPO / "scripts" / "plain_math.py"
SUFFIXES = (".typ", ".tex", ".py")
MAX_LISTED = 12


def load_checker():
    spec = importlib.util.spec_from_file_location("plain_math", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves the module through sys.modules while it executes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def written_lines(tool_input: dict, text: str) -> set[int] | None:
    """Line numbers the tool wrote, or None for the whole file."""
    if "content" in tool_input:
        return None
    new = tool_input.get("new_string")
    lines = set()
    start = text.find(new) if isinstance(new, str) and new else -1
    while start != -1:
        first = text.count("\n", 0, start) + 1
        lines.update(range(first, first + new.count("\n") + 1))
        start = text.find(new, start + 1)
    return lines


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    tool_input = data.get("tool_input") if isinstance(data, dict) else None
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not (isinstance(path, str) and path.endswith(SUFFIXES)):
        return
    resolved = Path(os.path.realpath(path))
    # This repo's own fixtures are stand-ins on purpose.
    if resolved.is_relative_to(REPO) or not resolved.is_file():
        return
    try:
        plain_math = load_checker()
        text = resolved.read_text(encoding="utf-8")
        findings = plain_math.check_file(resolved)
    except Exception:  # noqa: BLE001 -- a feedback hook must never stop an edit
        return
    wrote = written_lines(tool_input, text)
    here = [f for f in findings if wrote is None or f.line in wrote]
    if not here:
        return
    header = (
        f"Plain-text math in {resolved.name}: typeset each as math, or add a "
        "`math-ok: <reason>` comment on its line."
    )
    lines = [header]
    lines += [
        "  " + plain_math.format_finding("line", f).removeprefix("line:")
        for f in here[:MAX_LISTED]
    ]
    if len(here) > MAX_LISTED:
        lines.append(f"  (+{len(here) - MAX_LISTED} more)")
    if len(findings) > len(here):
        lines.append(
            f"{len(findings) - len(here)} more elsewhere in the file "
            "(`plain-math` task in agent-config lists them)."
        )
    print(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


if __name__ == "__main__":
    main()
