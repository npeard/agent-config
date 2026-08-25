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
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKER = re.compile(r"^#\s*claude-hook:\s*(?P<event>\w+)(?:\s+(?P<matcher>\S+))?\s*$")
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
# Hooks must run under the project's own interpreter, not whatever `python3`
# the machine ships -- on macOS that is 3.9, below the declared floor.
INTERPRETER = REPO / ".pixi" / "envs" / "dev" / "bin" / "python"
HOOKS_DIR = REPO / "hooks"


def declared_hooks(hooks_dir=HOOKS_DIR):
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


def undeclared(hooks_dir=HOOKS_DIR):
    declared = {name for name, _, _ in declared_hooks(hooks_dir)}
    return sorted(p.name for p in hooks_dir.glob("*.py") if p.name not in declared)


def command_for(filename):
    return f"{INTERPRETER} {HOOKS_DIR / filename}"


def repo_hook_in(command):
    """The name of the hook in this repo that `command` runs, else None.

    Deliberately narrower than `invokes`: this answers "is this registration
    mine to delete", and only a path inside this repo's hooks directory is.
    A command naming a hook by some other path may belong to another tool or
    to a previous clone, and removing it would be destroying someone else's
    configuration rather than tidying up after this one.
    """
    for token in str(command).split():
        path = Path(token)
        if path.parent == HOOKS_DIR:
            return path.name
    return None


def invokes(command, filename):
    """Whether a settings command runs exactly this hook file.

    Compared basename by basename over the command's tokens, not with `in`:
    substring matching let a new `list.py` claim `task-list.py`'s existing
    registration and overwrite its command, silently unregistering a live
    hook while reporting nothing. Tokens rather than the whole string so a
    command that passes arguments after the script still matches, and so an
    old absolute path from a previous clone location still matches -- that
    is the case the interpreter rewrite exists for.
    """
    return any(Path(token).name == filename for token in str(command).split())


def prune(settings, hooks):
    """Drop registrations of repo hooks that are no longer declared.

    Registration used to be add-only: nothing scanned the registry for
    commands naming a hook that no longer exists, so a deleted hook stayed
    registered forever and a renamed one registered twice, one of the two
    pointing at a file that was gone. A missing declaration for an event the
    hook once had is the same defect seen from the other side.
    """
    changes = []
    registry = settings.get("hooks", {})
    declared = {(name, event) for name, event, _ in hooks}
    for event in list(registry):
        surviving = []
        for entry in registry[event]:
            registered = entry.get("hooks", [])
            keep = []
            for hook in registered:
                name = repo_hook_in(hook.get("command", ""))
                if name is not None and (name, event) not in declared:
                    changes.append(f"unregistered {event} -> {name}")
                else:
                    keep.append(hook)
            if len(keep) != len(registered):
                entry["hooks"] = keep
            # An entry with nothing left to run is a husk whose matcher would
            # stay registered; one that never listed a command is not ours.
            if keep or not registered:
                surviving.append(entry)
        if surviving:
            registry[event] = surviving
        else:
            del registry[event]
    return changes


def apply(settings, hooks):
    """Converge a settings dict on `hooks`. Returns a list of change strings.

    Additions and removals are one call because a caller who can forget the
    second gets exactly the add-only behaviour that let dead registrations
    accumulate; `--check` reports whatever this returns.
    """
    changes = []
    registry = settings.setdefault("hooks", {})
    for filename, event, matcher in hooks:
        wanted = command_for(filename)
        entries = registry.setdefault(event, [])
        # Every match, not just the first. Stopping at the first left an old
        # clone's registration beside the rewritten one on a machine whose
        # checkout had moved: two entries, identical commands, the hook
        # firing twice per tool call, and every later run reporting "already
        # registered". prune() cannot reach those -- the name is declared.
        matches = [
            (entry, hook)
            for entry in entries
            for hook in entry.get("hooks", [])
            if invokes(hook.get("command", ""), filename)
        ]
        existing, duplicates = (matches[0], matches[1:]) if matches else (None, [])
        for entry, hook in duplicates:
            entry["hooks"].remove(hook)
            changes.append(f"removed duplicate {event} -> {filename}")
        # A hook is the only thing an entry exists to run, so one left empty
        # would keep its matcher registered against nothing.
        entries[:] = [entry for entry in entries if entry.get("hooks") != []]
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
    return changes + prune(settings, hooks)


def backup_path(settings):
    """A dated, non-colliding name for the copy taken before a write.

    The name was a fixed `.bak`, so a second run destroyed the only copy of
    the state the first run replaced -- and three generations of real
    settings backups had already been lost that way. The serial covers two
    runs inside one second, which is exactly what a test does.
    """
    # Local time via `time`, matching install.sh's `date` -- these names are
    # read by a person deciding which backup to restore.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = settings.with_name(f"{settings.name}.{stamp}.bak")
    serial = 0
    while candidate.exists():
        serial += 1
        candidate = settings.with_name(f"{settings.name}.{stamp}-{serial}.bak")
    return candidate


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

    existed = args.settings.is_file()
    if existed:
        try:
            settings = json.loads(args.settings.read_text())
        except ValueError:
            print(f"{args.settings} is not valid JSON; refusing to touch it.")
            return 1
    else:
        # A machine with no settings.json is a new machine, which is when
        # registration matters most. Reporting "nothing to do" and exiting 0
        # here brought one up with zero hooks and a success message -- the
        # never-wired-up failure this script exists to prevent -- and made
        # --check answer "registered" on the same machine.
        settings = {}

    changes = apply(settings, hooks)
    if not changes:
        print(f"Hooks already registered ({len(hooks)}).")
        return 0

    if args.check:
        print("Hook registration is out of date:")
        for change in changes:
            print(f"  {change}")
        return 1

    if existed:
        # Back up before the first write, matching install.sh's habit of
        # preserving anything it would otherwise overwrite.
        backup = backup_path(args.settings)
        shutil.copyfile(args.settings, backup)
    else:
        backup = None
        args.settings.parent.mkdir(parents=True, exist_ok=True)
    args.settings.write_text(json.dumps(settings, indent=2) + "\n")
    for change in changes:
        print(f"  {change}")
    if backup is not None:
        print(f"  backed up -> {backup.name}")
    else:
        print(f"  created {args.settings}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
