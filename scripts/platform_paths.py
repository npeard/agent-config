"""Where every platform difference this repo cares about is decided.

Kept in one place because the same three assumptions -- the pixi interpreter
layout, that a link is a symlink, and that reads are UTF-8 -- were repeated
across install, hook registration, preflight and the audit, so a Windows fix
in one left the others wrong.

Hooks are spawned standalone with an arbitrary cwd, so most stay
self-contained and do not import this; the duplication that costs is held
in check by a shared test fixture instead. environment-drift.py is the
exception: it loads this module, and the scripts that need it, by absolute
path from its own checkout, so the cwd cannot break it, and like them this
module is stdlib-only.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"


def dev_env(repo: Path) -> Path:
    return Path(repo) / ".pixi" / "envs" / "dev"


def windows_interpreter(repo: Path) -> Path:
    """The dev interpreter as Windows lays it out, whatever host we run on."""
    return dev_env(repo) / "python.exe"


def posix_interpreter(repo: Path) -> Path:
    """The dev interpreter as macOS/Linux lay it out, whatever host we run on."""
    return dev_env(repo) / "bin" / "python"


def interpreter(repo: Path) -> Path:
    """Path to the dev environment's Python, for the host running now.

    pixi puts the interpreter at the env root on Windows and under bin/
    everywhere else. Hardcoding the POSIX form made `register_hooks.py`
    abort on every Windows run.

    Use this when the answer is consumed by this process or written for this
    machine. A config naming *both* layouts at once -- Codex hooks.json, which
    carries a `command` and a `commandWindows` per handler -- must ask for the
    two forms explicitly, because this function cannot see a platform it is
    not running on and would otherwise write the same path into both fields.
    """
    return windows_interpreter(repo) if WINDOWS else posix_interpreter(repo)


def vscode_user_dir(home: Path) -> Path:
    """VS Code's per-user settings directory, which holds
    globalStorage/state.vscdb -- where the global disabled-extensions list
    lives, read by vscode_extensions.py.

    A pure function of `home`, like the rest of this module, rather than
    reading %APPDATA% or $XDG_CONFIG_HOME: those coincide with the standard
    per-OS layout below in the overwhelming common case, and a pure function
    is what lets a test supply an arbitrary home without touching the real
    environment.
    """
    home = Path(home)
    if WINDOWS:
        return home / "AppData" / "Roaming" / "Code" / "User"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Code" / "User"
    return home / ".config" / "Code" / "User"


def load_sibling(name: str):
    """The module ``name`` beside this file, loaded by path, and loaded once.

    By path because the SessionStart hook runs from an arbitrary cwd, so
    sys.path cannot find these scripts. Registered in sys.modules before it
    runs, because dataclasses look their own module up there while a class
    is built, and reused when already registered, so the hook and the
    modules it loads share one copy of each.
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, Path(__file__).resolve().parent / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
    return sys.modules[name]


def git_output(root: Path, *args: str, timeout: float) -> str | None:
    """git's stdout in root, or None when git fails, is absent or overruns.

    The timeout is required because installation_checkout sits on the
    SessionStart hook's path, where a wedged git would hang the session.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None


def installation_checkout(root: Path, *, timeout: float) -> Path:
    """Resolve a git worktree to its main checkout.

    Installed skills link into the main checkout, and VS Code's IDE lock
    names the folder its window has open, which for an agent in a worktree
    is the main checkout too. The first porcelain record is the main
    checkout; NUL delimiters preserve spaces and avoid Git's quoting of
    unusual paths, and a bare repo owns no install. ``timeout`` bounds git:
    preflight can wait longer than the SessionStart hook can.
    """
    root = Path(root).resolve()
    if not (root / ".git").is_file():
        return root
    listing = git_output(root, "worktree", "list", "--porcelain", "-z", timeout=timeout)
    listing = (listing or "").strip("\0")
    if listing:
        main = listing.split("\0\0", 1)[0].split("\0")
        if main[0].startswith("worktree ") and "bare" not in main:
            return Path(main[0].removeprefix("worktree ")).resolve()
    return root


def pid_alive(pid: int) -> bool:
    """Whether a process with this pid is currently running.

    Signal 0 is the standard liveness probe on POSIX, but os.kill on
    Windows routes any signal other than the two console events through
    TerminateProcess -- so the probe would kill the very process it asks
    about. Opening the process handle answers the same question there
    without touching it.
    """
    if WINDOWS:
        import ctypes

        query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # Alive but not ours (PermissionError), or an otherwise unusable
        # pid. Neither is evidence of death.
        return True
    return True


def link_dir(src: Path, dest: Path) -> None:
    """Point dest at the directory src.

    A junction on Windows: it needs no elevation and no Developer Mode,
    which os.symlink does (WinError 1314). Directory junctions cannot span
    to files, which is why CLAUDE.md is installed as an @import stub rather
    than a link.
    """
    src = Path(src).resolve()
    dest = Path(dest)
    if WINDOWS:
        # /J is the unprivileged form. mklink is a cmd builtin, so it cannot
        # be exec'd directly.
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(dest), str(src)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise OSError(f"mklink failed for {dest} -> {src}: {result.stderr.strip()}")
        if not is_link(dest):
            raise OSError(
                f"mklink reported success but {dest} is not a junction "
                f"(produced a non-link, e.g. a plain directory, for {dest} -> {src})"
            )
        return
    dest.symlink_to(src, target_is_directory=True)


def is_link(p: Path) -> bool:
    """Whether p is a link of any kind this repo creates."""
    p = Path(p)
    return p.is_symlink() or (WINDOWS and p.is_junction())


def link_target(p: Path) -> Path | None:
    """What p points at, or None when p is not a link.

    os.readlink() on a Windows junction returns an extended-length path
    prefixed "\\\\?\\" (e.g. "\\\\?\\C:\\repo"). resolve() does not strip
    this -- it is preserved through resolve(), producing a path that
    compares unequal to the plain form link_dir() was given -- so the
    prefix is stripped here before resolving.

    A relative target is anchored to the link's own directory, which is what
    the OS does when it follows one. resolve() alone anchors it to the
    process's cwd instead, so the same link read from two directories gave
    two different answers -- and preflight, which runs from wherever the user
    invoked it, would have called a good link a copy.
    """
    p = Path(p)
    if not is_link(p):
        return None
    try:
        raw = os.readlink(p)
    except OSError:
        return None
    target = Path(raw.removeprefix("\\\\?\\"))
    return (target if target.is_absolute() else p.parent / target).resolve()


def verify_link(p: Path, repo: Path) -> bool:
    """Whether p is genuinely a link into repo, rather than a copy of it.

    The check exists because Git Bash's `ln -s` does not fail on a Windows
    machine without Developer Mode -- it deep-copies and reports success. A
    copy is worse than a failure: it looks installed, and then silently
    stops tracking edits to the repo.
    """
    p, repo = Path(p), Path(repo).resolve()
    if not p.exists() or not is_link(p):
        return False
    target = link_target(p)
    if target is None:
        return False
    return repo == target or repo in target.parents
