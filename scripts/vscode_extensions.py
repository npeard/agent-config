#!/usr/bin/env python
"""Report drift between this machine's VS Code extensions and the standard set.

Two incidents motivated this. `olavovieiradecarvalho.notebook-mcp-server`
reported notebook writes that never reached disk, and cost about 4 hours
before that was noticed (ledger:
notebooks-skill-names-a-server-that-loses-writes). And nothing anywhere
stated which extensions this machine is expected to have at all, so an
agent has gone looking for tooling that was simply never installed.

`vscode-extensions.toml` at the repo root holds the standard set, each
entry with a `reason`, so a change to it is a decision rather than drift.
Everything unlisted is allowed and never reported.

Stdlib-only, and every external effect -- `code --list-extensions`, the
global disabled-extensions list, the IDE lock, process liveness, the
environment -- is an injected callable or mapping, so tests never touch
the real VS Code state db, spawn a real `code`, or read a real IDE lock.

Usage:
    python scripts/vscode_extensions.py [STANDARD_TOML] [--root ROOT]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_platform_paths():
    spec = importlib.util.spec_from_file_location(
        "platform_paths", Path(__file__).resolve().parent / "platform_paths.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_paths = _load_platform_paths()


@dataclass(frozen=True)
class Standard:
    required: dict[str, str]
    forbidden: dict[str, str]


def load_standard(path: Path) -> Standard:
    """Load the expected extension set from TOML.

    Ids are lowercased on load, once, here -- `code --list-extensions` and
    the disabled-list db both report ids in whatever case VS Code stored
    them, and comparing case-sensitively would let a real match silently
    read as absent.
    """
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        str(ext_id).lower(): str(entry["reason"])
        for ext_id, entry in data.get("required", {}).items()
    }
    forbidden = {
        str(ext_id).lower(): str(entry["reason"])
        for ext_id, entry in data.get("forbidden", {}).items()
    }
    return Standard(required=required, forbidden=forbidden)


@dataclass(frozen=True)
class ExtReport:
    applicable: bool
    missing: list[str]
    disabled_required: list[str]
    forbidden_active: list[tuple[str, str]]
    ide: str | None
    notes: list[str]


def read_disabled_from(db: Path) -> set[str] | None:
    """Globally disabled extension ids, or None when that cannot be known.

    Opened read-only (`mode=ro`) so a running VS Code -- which holds this
    file open -- is never contended with, and so this script can never be
    the thing that corrupts a db it does not own. A locked or missing file,
    or a value that is not the JSON this key is supposed to hold, is
    "unknown", which the caller must tell apart from a real empty list of
    disables: workspace-level disables are separate and not read here.
    """
    db = Path(db)
    if not db.is_file():
        return None
    uri = f"{db.resolve().as_uri()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=1)
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = ?",
                ("extensionsIdentifiers/disabled",),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if row is None:
        # The key is simply absent -- a known, empty answer, not "unknown".
        return set()
    try:
        entries = json.loads(row[0])
    except (ValueError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    return {
        str(entry["id"]).lower()
        for entry in entries
        if isinstance(entry, dict) and "id" in entry
    }


def _normalize_path(path: Path) -> str:
    """A form of `path` that compares equal across the spellings the same
    location can have -- a Windows-lowercased drive letter, a differing
    case elsewhere, a relative segment, or a trailing separator.

    normcase lowercases and normalizes separators on Windows, where the
    filesystem is case-insensitive, and is a no-op on POSIX, where it is
    not -- exactly the "case-folded" comparison Review Focus 5 asks for,
    without hand-rolling a per-OS rule this repo already keeps in one
    place (platform_paths.WINDOWS).
    """
    return os.path.normcase(str(Path(path).resolve()))


_IDE_PROBLEM = "Claude Code IDE integration not connected to this workspace"


def _check_ide(
    root: Path,
    *,
    ide_dir: Path,
    env: Mapping[str, str],
    pid_alive: Callable[[int], bool],
) -> str | None:
    """(problem text, or None when fine or not applicable).

    Only checked for Claude Code (which sets `CLAUDECODE`) inside a VS Code
    terminal, where `CLAUDE_CODE_SSE_PORT` is meaningful at all: the hook
    also runs under Codex, which never sets it. The project matches when
    it, or the main checkout of its worktree, is at or under a workspace
    folder, since a window opened on a parent directory serves it too. The
    lock's `authToken` is read here (it is the whole file) but never placed
    in the return value -- it must never reach any output.
    """
    if not env.get("CLAUDECODE") or env.get("TERM_PROGRAM") != "vscode":
        return None
    port = env.get("CLAUDE_CODE_SSE_PORT")
    if not port:
        return _IDE_PROBLEM
    lock_path = Path(ide_dir) / f"{port}.lock"
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _IDE_PROBLEM
    pid = data.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return _IDE_PROBLEM
    folders = data.get("workspaceFolders")
    if not isinstance(folders, list):
        return _IDE_PROBLEM
    targets = [
        Path(_normalize_path(p))
        for p in (root, platform_paths.installation_checkout(root))
    ]
    if not any(
        isinstance(folder, str) and target.is_relative_to(_normalize_path(Path(folder)))
        for folder in folders
        for target in targets
    ):
        return _IDE_PROBLEM
    return None


def check(
    standard: Standard,
    *,
    root: Path,
    run: Callable[[list[str]], subprocess.CompletedProcess | None],
    read_disabled: Callable[[], set[str] | None],
    ide_dir: Path,
    env: Mapping[str, str],
    pid_alive: Callable[[int], bool],
) -> ExtReport:
    result = run(["code", "--list-extensions"])
    if result is None:
        # No `code` on PATH means no VS Code on this machine -- not an
        # error, and there is nothing left to check.
        return ExtReport(
            applicable=False,
            missing=[],
            disabled_required=[],
            forbidden_active=[],
            ide=None,
            notes=[],
        )

    installed = {
        line.strip().lower() for line in result.stdout.splitlines() if line.strip()
    }
    disabled = read_disabled()
    enabled_unknown = disabled is None

    missing = sorted(ext for ext in standard.required if ext not in installed)
    disabled_required = sorted(
        ext
        for ext in standard.required
        if ext in installed and disabled is not None and ext in disabled
    )
    forbidden_active = sorted(
        (ext, reason)
        for ext, reason in standard.forbidden.items()
        if ext in installed and (disabled is None or ext not in disabled)
    )

    notes = []
    if enabled_unknown:
        notes.append(
            "enabled state unknown (VS Code state db locked or missing): missing "
            "extensions are still reported, and forbidden ones are reported as "
            "installed"
        )
    notes.append("workspace-level disables are not read, only the global list")

    ide = _check_ide(root, ide_dir=ide_dir, env=env, pid_alive=pid_alive)

    return ExtReport(
        applicable=True,
        missing=missing,
        disabled_required=disabled_required,
        forbidden_active=forbidden_active,
        ide=ide,
        notes=notes,
    )


def problem_count(report: ExtReport) -> int:
    """How many things to tell the user; notes alone are not problems.

    Shared with preflight and the SessionStart hook, which stay silent at
    zero, so render's count and their silence cannot disagree.
    """
    return (
        len(report.missing)
        + len(report.disabled_required)
        + len(report.forbidden_active)
        + (1 if report.ide else 0)
    )


def render(report: ExtReport) -> tuple[str, list[str]]:
    if not report.applicable:
        return "VS Code extensions: not applicable (code not on PATH)", []

    lines: list[str] = []
    for ext in report.missing:
        lines.append(f"missing (required): {ext}")
    for ext in report.disabled_required:
        lines.append(f"disabled (required): {ext}")
    for ext, reason in report.forbidden_active:
        lines.append(f"forbidden, installed and enabled: {ext} -- {reason}")
    if report.ide:
        lines.append(report.ide)

    problems = problem_count(report)
    summary = (
        "VS Code extensions: ok"
        if not problems
        else f"VS Code extensions: {problems} problem(s)"
    )
    lines.extend(report.notes)
    return summary, lines


def _run_code(argv: list[str]) -> subprocess.CompletedProcess | None:
    """Run `code` for real, or None when it is not on PATH.

    Resolved with shutil.which first rather than handed to subprocess.run
    as a bare name: VS Code installs `code` on Windows as `code.cmd`, and
    CreateProcess -- unlike a shell -- does not consult PATHEXT to find it,
    so the bare name raises FileNotFoundError there even though `code` is
    genuinely on PATH and a shell invocation of it works.

    A missing `code` means this machine has no VS Code -- the whole check
    is skipped, silently, for exactly that reason -- so the failure this
    catches is reported through the return value, not an exception.
    """
    exe = shutil.which(argv[0])
    if exe is None:
        return None
    try:
        return subprocess.run(
            [exe, *argv[1:]], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None


def live_check(
    standard: Standard, root: Path, *, home: Path, env: Mapping[str, str]
) -> ExtReport:
    """check() with this machine's real effects: `code`, VS Code's state db
    and the IDE locks under `home`, and real pid liveness. The one wiring
    shared by main, preflight and the SessionStart hook."""
    db = platform_paths.vscode_user_dir(home) / "globalStorage" / "state.vscdb"
    return check(
        standard,
        root=root,
        run=_run_code,
        read_disabled=lambda: read_disabled_from(db),
        ide_dir=home / ".claude" / "ide",
        env=env,
        pid_alive=platform_paths.pid_alive,
    )


def _repo_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return Path.cwd()
    return Path(out.stdout.strip() or ".")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "standard",
        nargs="?",
        type=Path,
        help="path to vscode-extensions.toml (default: this repo's own)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="project root matched against the IDE lock's workspaceFolders "
        "(default: the current git checkout, or cwd)",
    )
    args = parser.parse_args(argv)

    toml_path = args.standard or (REPO / "vscode-extensions.toml")
    try:
        standard = load_standard(toml_path)
    except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        print(f"could not load {toml_path}: {exc}", file=sys.stderr)
        return 1

    root = args.root or _repo_root()
    report = live_check(standard, root, home=Path.home(), env=os.environ)
    summary, lines = render(report)
    print(summary)
    for line in lines:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
