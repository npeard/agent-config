#!/usr/bin/env python3
"""Register this repo's hooks in ~/.claude/settings.json.

Registration was manual, and a manual step that nothing verifies is a step
that eventually gets skipped: `task-list.py` was written, tested, documented
as registered, and never wired up, while the rule it replaced was deleted.
Automating it removes the step rather than reminding anyone about it.

Each hook declares its own event in a marker comment near the top:

    # claude-hook: SessionStart
    # claude-hook: PostToolUse Write|Edit

Keeping the declaration in the hook means it cannot drift from the file it
describes, and a new hook cannot be added without saying when it runs.

A hook may carry several markers and so register under several events. One
notification hook answering Stop, Notification and PreToolUse is one set of
sound preferences in one file; splitting it into three files to satisfy the
parser would give three copies of that table to keep in agreement.

Run by install.sh through the project's own interpreter, after the dev
environment has been materialized. That ordering is not incidental: a
registered hook names `.pixi/envs/dev/bin/python` in its command, so writing
the registration before that binary exists produces hooks that cannot start
-- which is what an earlier version did, while reporting success.

Usage:
    pixi run register-hooks [--check] [--settings PATH]

Invoked through the task runner or install.sh, both of which supply the
project interpreter. A bare `python3` would be whatever the machine ships.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKER = re.compile(r"^#\s*claude-hook:\s*(?P<event>\w+)(?:\s+(?P<matcher>\S+))?\s*$")
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
# Hooks must run under the project's own interpreter, not whatever `python3`
# the machine ships -- on macOS that is 3.9, below the declared floor.
INTERPRETER = REPO / ".pixi" / "envs" / "dev" / "bin" / "python"


def declared_hooks(hooks_dir=REPO / "hooks"):
    """[(filename, event, matcher_or_None)] for every marker in every hook.

    Every marker in the window is collected, not just the first, so one file
    can serve several events. Order follows the file, which is the order the
    events are registered in.
    """
    found = []
    for path in sorted(hooks_dir.glob("*.py")):
        for line in path.read_text(errors="replace").splitlines()[:10]:
            match = MARKER.match(line.strip())
            if match:
                found.append((path.name, match.group("event"), match.group("matcher")))
    return found


def undeclared(hooks_dir=REPO / "hooks"):
    declared = {name for name, _, _ in declared_hooks(hooks_dir)}
    return sorted(p.name for p in hooks_dir.glob("*.py") if p.name not in declared)


def command_for(filename):
    return f"{INTERPRETER} {REPO / 'hooks' / filename}"


def apply(settings, hooks):
    """Merge hooks into a settings dict. Returns a list of change strings."""
    changes = []
    registry = settings.setdefault("hooks", {})
    for filename, event, matcher in hooks:
        wanted = command_for(filename)
        entries = registry.setdefault(event, [])
        existing = None
        for entry in entries:
            for hook in entry.get("hooks", []):
                if filename in str(hook.get("command", "")):
                    existing = (entry, hook)
                    break
            if existing:
                break
        if existing is None:
            entry = {"hooks": [{"type": "command", "command": wanted, "timeout": 10}]}
            if matcher:
                entry["matcher"] = matcher
            entries.append(entry)
            changes.append(f"registered {event} -> {filename}")
            continue
        entry, hook = existing
        if hook.get("command") != wanted:
            hook["command"] = wanted
            changes.append(f"updated {event} -> {filename} (interpreter)")
        if matcher and entry.get("matcher") != matcher:
            entry["matcher"] = matcher
            changes.append(f"updated {event} -> {filename} (matcher)")
    return changes


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report, do not write")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    args = parser.parse_args(argv)

    missing_declaration = undeclared()
    if missing_declaration:
        print("Hooks with no `# claude-hook:` marker, so they cannot be registered:")
        for name in missing_declaration:
            print(f"  {name}")
        return 1

    hooks = declared_hooks()
    if not hooks:
        print("No hooks declared.")
        return 0

    if not INTERPRETER.exists():
        # Refuse rather than warn: a hook whose interpreter is missing is
        # silently dead, and a registration that reports success while
        # producing that is worse than no registration.
        print(f"Interpreter {INTERPRETER} does not exist.")
        print("Run `pixi install -e dev` first, or use ./install.sh.")
        return 1

    if not args.settings.is_file():
        print(f"No settings file at {args.settings}; nothing to do.")
        return 0

    original = args.settings.read_text()
    try:
        settings = json.loads(original)
    except ValueError:
        print(f"{args.settings} is not valid JSON; refusing to touch it.")
        return 1

    changes = apply(settings, hooks)
    if not changes:
        print(f"Hooks already registered ({len(hooks)}).")
        return 0

    if args.check:
        print("Hook registration is out of date:")
        for change in changes:
            print(f"  {change}")
        return 1

    # Back up before the first write, matching install.sh's habit of
    # preserving anything it would otherwise overwrite.
    shutil.copyfile(args.settings, args.settings.with_suffix(".json.bak"))
    args.settings.write_text(json.dumps(settings, indent=2) + "\n")
    for change in changes:
        print(f"  {change}")
    print(f"  backed up -> {args.settings.with_suffix('.json.bak').name}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
