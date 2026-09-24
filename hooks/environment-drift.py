#!/usr/bin/env python3
# claude-hook: SessionStart
"""Tell the session about dependency updates and VS Code extension drift.

Both were found by the user rather than by tooling: an agent said "no torch
2.14 anywhere" after querying only conda-forge while PyPI had it (doqs
session e0f19169), and an unwanted notebook extension reported writes that
never reached disk. preflight reports the same rows, but only when someone
runs it; this puts them in front of every session.

The logic lives in scripts/dep_updates.py and scripts/vscode_extensions.py,
loaded by path from this hook's own checkout, so the hook and preflight
cannot disagree. Silent when there is nothing to report, following
task-list.py: an always-present block teaches the reader to skip it.

It never waits on the network. A cold dependency check takes ~25 s on
doqs, most of it `pixi list`, so the hook reads only the cache and, when
that is stale or absent, starts `dep_updates.py --refresh` detached and
says the result arrives next session. The refresh owns the lock, the
atomic cache write and the cleanup of its own children; the hook only
launches it. The extension check runs inline because `code
--list-extensions` answers in under a second.

Trust boundary: this emits into SessionStart context, in every project.
The only subprocess it starts is the refresh, whose output goes to DEVNULL
and is never read. What it emits is dep_updates.render (versions, wheel
tags and whitespace-collapsed spec/solver text; its own ledger entry says
what bounds each) and vscode_extensions.render (ids and reasons from this
repo's own TOML, since only listed extensions are ever reported, and a
fixed IDE message -- never the IDE lock's authToken). Nothing read is executed.

Stdlib-only, like every hook here: its interpreter is named in
~/.claude/settings.json, outside this repo's checks (see task-list.py).
The scripts it loads are stdlib-only for the same reason. Any internal
error prints nothing and exits 0, since a broken drift check must never
cost a session.
"""

import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
SCRIPTS = CHECKOUT / "scripts"
STANDARD = CHECKOUT / "vscode-extensions.toml"
log = logging.getLogger("environment-drift")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their own module up in sys.modules while building.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


try:
    platform_paths = _load("platform_paths")
    dep_updates = _load("dep_updates")
    vscode_extensions = _load("vscode_extensions")
except Exception:
    # A broken checkout must not cost the session: log to stderr, which the
    # host keeps out of the session's context, and let main() stay silent.
    log.exception("could not load its scripts")
    platform_paths = dep_updates = vscode_extensions = None


def spawn_refresh(argv):
    """Start argv detached, with no inherited stdio, and do not wait.

    Detached so the session's exit does not kill it, and with stdio on
    DEVNULL so the host, which reads this hook's stdout to EOF, is not held
    open until the refresh finishes.
    """
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        extra = {"creationflags": flags}
    else:
        extra = {"start_new_session": True}
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **extra,
    )


def _block(summary, lines):
    return "\n".join([summary, *(f"  {line}" for line in lines)])


def context(root, *, spawn, now, home, env):
    """The additionalContext text, or None when there is nothing to say."""
    blocks = []
    deps = dep_updates.cached(root, now=now)
    if deps is None:
        spawn([sys.executable, str(SCRIPTS / "dep_updates.py"), str(root), "--refresh"])
        blocks.append(
            "dependency updates: cache stale or absent; a background refresh "
            "started, and its result arrives next session or on the next "
            "preflight run"
        )
    elif deps.applicable and not dep_updates.is_clean(deps):
        blocks.append(_block(*dep_updates.render(deps, root)))
    if STANDARD.is_file():
        exts = vscode_extensions.live_check(
            vscode_extensions.load_standard(STANDARD),
            root,
            home=home,
            env=env,
        )
        if exts.applicable and vscode_extensions.problem_count(exts):
            blocks.append(_block(*vscode_extensions.render(exts)))
    return "\n".join(blocks) if blocks else None


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    try:
        text = context(
            Path(cwd or Path.cwd()),
            spawn=spawn_refresh,
            now=time.time(),
            home=Path.home(),
            env=os.environ,
        )
    except Exception:
        # Never cost a session over a drift check; the traceback goes to
        # stderr for whoever debugs the hook, and stdout stays empty.
        log.exception("check failed")
        return
    if text:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": text,
                    }
                }
            )
        )


if __name__ == "__main__":
    main()
