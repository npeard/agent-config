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
# A name longer than this is not a task anyone types, so refusing it bounds
# how much a crafted manifest can push into context. Kept well above any real
# name: at 40 it silently swallowed ordinary 45-character npm scripts.
MAX_NAME = 120
# The longest name no longer sets the indent for every other line, so one
# 100-character name costs one long line instead of padding twenty.
MAX_WIDTH = 24


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
    # TypeError as well: {"scripts": 5} decodes fine and then is not
    # iterable, so any project the user opens could kill this hook.
    try:
        return dict(json.loads(text).get("scripts", {}))
    except (ValueError, AttributeError, TypeError):
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


# A task name is something you type after `pixi run`, so it is a shell word.
# Four of the five parsers already enforce that by charset; json_scripts cannot,
# because package.json keys are arbitrary JSON strings -- newlines included.
# A crafted manifest therefore injected free-standing prose into SessionStart
# context, the highest-trust position in the window, in every project this hook
# fires in. MAX_DEF did not help: it caps the definition, never the name.
#
# Filtered here rather than inside json_scripts because discover() is the one
# place every parser's output converges, so a parser added later cannot
# reintroduce the hole.
#
# The charset is the security property and is deliberately an allowlist. A task
# name is not just text in context, it is text the reader is invited to type
# after `npm run`, so a name carrying `;`, `|`, `$(` or a backtick would be
# command injection at the point of use. Length is a separate concern and now
# lives in MAX_NAME: bundling the two inside this regex is what made a
# legitimate 45-character script indistinguishable from an attack.
SAFE_NAME = re.compile(r"[A-Za-z0-9_.:@/-]+\Z")


def safe_definition(value):
    """Whitespace collapsed, then truncated.

    Truncation alone was not enough: a definition well under MAX_DEF can still
    contain a newline and break out of the list this renders into. Collapsing
    first means the cap is a cap on what is displayed, not on what is quoted.
    """
    collapsed = " ".join(str(value).split())
    if len(collapsed) > MAX_DEF:
        return collapsed[: MAX_DEF - 3] + "..."
    return collapsed


def usable(name) -> bool:
    name = str(name)
    return len(name) <= MAX_NAME and bool(SAFE_NAME.match(name))


def discover(root):
    """[(prefix, safe tasks, count refused)] per manifest present.

    The refused count is carried rather than discarded: a name this hook will
    not print is still a task the project has, and dropping it before render's
    accounting meant a project with one unprintable script saw no trace of it.
    An unexplained gap teaches the reader that this block is incomplete in
    ways they cannot see, which is worse than a name they have to go look up.
    """
    out = []
    for filename, prefix, parse in SOURCES:
        path = root / filename
        if not path.is_file():
            continue
        try:
            tasks = parse(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        kept = {n: v for n, v in tasks.items() if usable(n)}
        refused = len(tasks) - len(kept)
        if kept or refused:
            out.append((prefix, kept, refused))
    return out


def render(discovered):
    lines = []
    for prefix, tasks, refused in discovered:
        names = list(tasks)
        shown, hidden = names[:MAX_TASKS], names[MAX_TASKS:]
        lines.append(f"Task commands available ({prefix} <name>):")
        # default=0 because a manifest whose every name was refused reaches
        # here with nothing to show, and max() of an empty sequence raises --
        # killing the hook on exactly the input the refusal count exists for.
        width = min(max((len(n) for n in shown), default=0), MAX_WIDTH)
        for name in shown:
            definition = safe_definition(tasks[name])
            lines.append(
                f"  {name:<{width}}  {definition}" if definition else f"  {name}"
            )
        unshown = len(hidden) + refused
        if unshown:
            lines.append(f"  ... and {unshown} more")
    return "\n".join(lines)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        # json.load only raises for *malformed* JSON, so `5` or `null` decodes
        # fine and then has no .get. promotion-check.py and prose-writing.py
        # both cite this file as guarding "the identical call"; it did not.
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
