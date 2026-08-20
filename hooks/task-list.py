#!/usr/bin/env python3
# claude-hook: SessionStart
"""Tell the session which short-form task commands this project actually has.

Replaces a rule that said "use the project's short-form task commands" with
the information that rule was a proxy for. The observed violation was not
ignorance of the rule but not knowing that `pixi run format` existed and
covered the work, so naming the tasks is strictly more useful than asserting
that tasks exist.

Reads whichever manifest the project has, which is what lets one hook serve
projects with different runners: it knows about manifests, not about any
particular project.

Silent when no tasks are found. A project without a runner should pay
nothing, and an empty section only teaches the reader to skip this block.

TOML is parsed with a regex rather than tomllib, and the reason is narrower
than it looks: the interpreter that invokes a hook is named in
~/.claude/settings.json, a file outside this repo and outside its checks. A
hook that needs nothing beyond the standard library of any interpreter keeps
working when that file is wrong or stale, and a task list is worth having
approximately. Scripts under scripts/ face no such constraint and assume the
project's own environment.
"""

import json
import re
import sys
from pathlib import Path

MAX_TASKS = 20
MAX_DEF = 60


def task_definition(value):
    """Readable one-liner for a pixi task value.

    An inline table needs care: taking the first quoted string out of
    `{ depends-on = ["format", ...] }` renders the aggregate task as though
    it *were* its first dependency, which is worse than saying nothing.
    """
    value = value.strip()
    if not value.startswith("{"):
        quoted = re.search(r'"([^"]*)"', value)
        return quoted.group(1) if quoted else value
    cmd = re.search(r'cmd\s*=\s*"([^"]*)"', value)
    if cmd:
        return cmd.group(1)
    deps = re.search(r"depends-on\s*=\s*\[([^\]]*)\]", value)
    if deps:
        names = re.findall(r'"([^"]*)"', deps.group(1))
        return "runs: " + ", ".join(names)
    return "(composite)"


def pixi_tasks(text):
    """`[tasks]` and `[feature.<name>.tasks]` entries, in file order."""
    found = {}
    in_tasks = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped.strip("[]")
            in_tasks = section == "tasks" or re.fullmatch(
                r"feature\.[^.]+\.tasks", section
            )
            continue
        if not in_tasks or "=" not in stripped or stripped.startswith("#"):
            continue
        name, _, value = stripped.partition("=")
        name, value = name.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            continue
        found[name] = task_definition(value)
    return found


def yaml_tasks(text):
    """Top-level keys under a `tasks:` mapping (Taskfile)."""
    found = {}
    in_tasks = False
    for line in text.splitlines():
        if re.match(r"^tasks:\s*$", line):
            in_tasks = True
            continue
        if in_tasks and line and not line[0].isspace():
            break
        m = re.match(r"^  ([A-Za-z0-9_:-]+):\s*$", line) if in_tasks else None
        if m:
            found[m.group(1)] = ""
    return found


def json_scripts(text):
    try:
        return dict(json.loads(text).get("scripts", {}))
    except (ValueError, AttributeError):
        return {}


def make_targets(text):
    names = re.findall(r"^([A-Za-z0-9_-]+):(?!=)", text, re.MULTILINE)
    return {n: "" for n in names if n != ".PHONY"}


def just_recipes(text):
    return {n: "" for n in re.findall(r"^([A-Za-z0-9_-]+):", text, re.MULTILINE)}


# (manifest, invocation prefix, parser). First match wins per manifest; all
# manifests present are reported, since a repo may legitimately have two.
SOURCES = (
    ("pixi.toml", "pixi run", pixi_tasks),
    ("Taskfile.yml", "task", yaml_tasks),
    ("package.json", "npm run", json_scripts),
    ("justfile", "just", just_recipes),
    ("Makefile", "make", make_targets),
)


def discover(root):
    out = []
    for filename, prefix, parse in SOURCES:
        path = root / filename
        if not path.is_file():
            continue
        try:
            tasks = parse(path.read_text(errors="replace"))
        except OSError:
            continue
        if tasks:
            out.append((prefix, tasks))
    return out


def render(discovered):
    lines = []
    for prefix, tasks in discovered:
        names = list(tasks)
        shown, hidden = names[:MAX_TASKS], names[MAX_TASKS:]
        lines.append(f"Task commands available ({prefix} <name>):")
        width = max(len(n) for n in shown)
        for name in shown:
            definition = tasks[name]
            if len(definition) > MAX_DEF:
                definition = definition[: MAX_DEF - 3] + "..."
            lines.append(
                f"  {name:<{width}}  {definition}" if definition else f"  {name}"
            )
        if hidden:
            lines.append(f"  ... and {len(hidden)} more")
    return "\n".join(lines)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    root = Path(payload.get("cwd") or Path.cwd())

    discovered = discover(root)
    if not discovered:
        return

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": render(discovered),
                }
            }
        )
    )


if __name__ == "__main__":
    main()
