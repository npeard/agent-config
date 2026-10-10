#!/usr/bin/env python3
"""Converge ~/.codex/hooks.json on this repository's supported hooks."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def _load_platform_paths():
    spec = importlib.util.spec_from_file_location(
        "platform_paths", Path(__file__).resolve().parent / "platform_paths.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_paths = _load_platform_paths()
REPO = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS = Path.home() / ".codex" / "hooks.json"


@dataclass(frozen=True)
class HookSpec:
    filename: str
    event: str
    matcher: str | None
    timeout: int = 10


CODEX_HOOKS = (
    HookSpec("task-list.py", "SessionStart", None),
    HookSpec("environment-drift.py", "SessionStart", None),
    HookSpec("prose-writing.py", "PreToolUse", "apply_patch|Bash"),
    HookSpec("promotion-check.py", "PostToolUse", "apply_patch|Bash"),
    HookSpec("prose-feedback.py", "PostToolUse", "apply_patch|Bash"),
    HookSpec("audit-owed.py", "PostToolUse", "Bash"),
    HookSpec("notify.py", "Stop", None),
)
_DECLARED_REPO = REPO


def declared_hooks(repo: Path) -> tuple[HookSpec, ...]:
    """The Codex-supported subset of the repository's existing hook programs."""
    global _DECLARED_REPO
    _DECLARED_REPO = Path(repo).resolve()
    return CODEX_HOOKS


def command_for(repo: Path, filename: str) -> tuple[str, str]:
    """Return quoted, absolute Unix and Windows command values for a hook.

    Both layouts are asked for by name rather than taken from
    `platform_paths.interpreter`, which answers for the host running now: a
    single hooks.json entry describes both platforms at once, so deriving one
    field from the live host wrote that host's path into both and left the
    other platform's command pointing at an interpreter that is not there.
    """
    repo = Path(repo).resolve()
    script = (repo / "hooks" / filename).resolve()
    unix = platform_paths.posix_interpreter(repo)
    windows = platform_paths.windows_interpreter(repo)
    return f'"{unix}" "{script}"', f'"{windows}" "{script}"'


def _paths_in(command: object) -> list[Path]:
    """Extract path-shaped quoted values without treating a basename as ownership."""
    if not isinstance(command, str):
        return []
    quoted = re.findall(r"[\"']([^\"']+)[\"']", command)
    return [Path(value).resolve() for value in quoted if Path(value).is_absolute()]


def _owned(handler: object, repo: Path) -> bool:
    """Whether a command names a hook path in this checkout, not merely its basename."""
    if not isinstance(handler, dict):
        return False
    hooks_dir = (Path(repo) / "hooks").resolve()
    for key in ("command", "commandWindows"):
        for path in _paths_in(handler.get(key)):
            if path.parent == hooks_dir and path.suffix == ".py":
                return True
    return False


def _handler(repo: Path, spec: HookSpec) -> dict[str, object]:
    command, command_windows = command_for(repo, spec.filename)
    return {
        "type": "command",
        "command": command,
        "commandWindows": command_windows,
        "timeout": spec.timeout,
    }


def apply(
    config: dict[str, object], hooks: tuple[HookSpec, ...] | list[HookSpec]
) -> list[str]:
    """Merge owned handlers, prune stale ones, and leave foreign configuration intact."""
    repo = _DECLARED_REPO
    before = json.dumps(config, sort_keys=True)

    for event, groups in list(config.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                kept_groups.append(group)
                continue
            remaining = [handler for handler in handlers if not _owned(handler, repo)]
            if remaining or not handlers:
                group["hooks"] = remaining
                kept_groups.append(group)
        config[event] = kept_groups

    for spec in hooks:
        groups = config.setdefault(spec.event, [])
        if not isinstance(groups, list):
            raise TypeError(f"{spec.event} must be a list of hook groups")
        group = next(
            (
                item
                for item in groups
                if isinstance(item, dict) and item.get("matcher") == spec.matcher
            ),
            None,
        )
        if group is None:
            group = {"hooks": []}
            if spec.matcher is not None:
                group["matcher"] = spec.matcher
            groups.append(group)
        group.setdefault("hooks", []).append(_handler(repo, spec))

    return (
        ["Codex hooks updated"] if json.dumps(config, sort_keys=True) != before else []
    )


def backup_path(settings: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = settings.with_name(f"{settings.name}.{stamp}.bak")
    serial = 0
    while candidate.exists():
        serial += 1
        candidate = settings.with_name(f"{settings.name}.{stamp}-{serial}.bak")
    return candidate


def _write_atomically(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()

    existed = args.settings.is_file()
    if existed:
        original = args.settings.read_bytes()
        try:
            config = json.loads(original)
        except json.JSONDecodeError:
            print(f"{args.settings} is not valid JSON; refusing to touch it.")
            return 1
    else:
        config = {}

    changes = apply(config, declared_hooks(repo))
    if not changes:
        print("Codex hooks already registered.")
        return 0
    if args.check:
        print("Codex hook registration is out of date.")
        return 1

    args.settings.parent.mkdir(parents=True, exist_ok=True)
    if existed:
        shutil.copyfile(args.settings, backup_path(args.settings))
    _write_atomically(args.settings, json.dumps(config, indent=2) + "\n")
    print("Codex hooks updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
