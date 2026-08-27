#!/usr/bin/env python
"""Install claude-config into ~/.claude. Safe to re-run, on any platform.

Ported from install.sh, which could not run outside a POSIX shell and whose
`ln -s` silently deep-copied on Windows -- printing "Linked ..." for a copy
that would never track another edit. Every link written here is verified
afterwards for that reason.

The ordering below is load-bearing and was arrived at by fixing real
failures: directories, then the CLAUDE.md stub, then skill links, then the
prune, then the pixi environment, and only then hook registration. Hooks
name the dev interpreter in their command, so registering before that
interpreter exists writes hooks that cannot start and reports success.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _load_platform_paths():
    """Import the sibling module without a package, and without a
    sys.path mutation `ruff --fix` would hoist above (E402) since this repo
    ships zero suppressions. Mirrors scripts/register_hooks.py's loader.
    """
    spec = importlib.util.spec_from_file_location(
        "platform_paths",
        Path(__file__).resolve().parent / "scripts" / "platform_paths.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


platform_paths = _load_platform_paths()

REPO = Path(__file__).resolve().parent
STUB = "@~/Documents/Projects/claude-config/CLAUDE.md\n"


def back_up(dest: Path) -> None:
    """Move dest aside under a dated name.

    Dated rather than a fixed .bak: with one name a second run destroyed the
    only copy of what the first replaced, and ~/.claude had already lost
    three generations of settings that way. The serial covers two runs
    inside one second, which is what a test does.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = dest.with_name(f"{dest.name}.{stamp}.bak")
    serial = 0
    while backup.exists():
        serial += 1
        backup = dest.with_name(f"{dest.name}.{stamp}-{serial}.bak")
    print(f"Backing up existing {dest} to {backup}")
    dest.rename(backup)


def clear(dest: Path) -> None:
    """Remove dest whatever it is: link, copy, or regular file."""
    if platform_paths.is_link(dest):
        # A junction is removed as a directory, a symlink as a file.
        if dest.is_dir() and not dest.is_symlink():
            dest.rmdir()
        else:
            dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    elif dest.exists():
        dest.unlink()


def install_stub(claude_dir: Path) -> None:
    """Write ~/.claude/CLAUDE.md as an @import of this repo's copy.

    A stub, not a link: it needs no privilege on any platform and behaves
    identically on both, so there is no second code path to keep in step.
    """
    dest = claude_dir / "CLAUDE.md"
    if dest.is_file() and not platform_paths.is_link(dest):
        if dest.read_text(encoding="utf-8") == STUB:
            print(f"{dest} already imports this repo")
            return
        back_up(dest)
    else:
        clear(dest)
    dest.write_text(STUB, encoding="utf-8")
    print(f"Wrote {dest} -> {STUB.strip()}")


def install_skills(claude_dir: Path) -> list[str]:
    """Link every skill this repo carries, and verify each one landed."""
    source = REPO / "skills"
    installed = claude_dir / "skills"
    installed.mkdir(parents=True, exist_ok=True)
    problems = []
    for src in sorted(p for p in source.iterdir() if p.is_dir()):
        dest = installed / src.name
        if (
            platform_paths.verify_link(dest, REPO)
            and platform_paths.link_target(dest) == src.resolve()
        ):
            continue
        clear(dest)
        try:
            platform_paths.link_dir(src, dest)
        except OSError as exc:
            problems.append(f"{src.name}: {exc}")
            continue
        # Verified, not trusted: a copy reports success just as loudly.
        if not platform_paths.verify_link(dest, REPO):
            problems.append(f"{src.name}: produced a copy rather than a link")
            continue
        print(f"Linked {dest} -> {src}")
    return problems


def prune(claude_dir: Path) -> None:
    """Drop links into this repo whose skill is gone.

    A renamed or deleted skill otherwise leaves its link behind, and a stale
    link is offered to every session as a real skill. Only links into this
    repo are pruned: another tool's links, and links from a clone kept
    elsewhere, are not ours to remove.
    """
    installed = claude_dir / "skills"
    if not installed.is_dir():
        return
    for p in sorted(installed.iterdir()):
        if not platform_paths.is_link(p):
            continue
        target = platform_paths.link_target(p)
        if target is None or (REPO / "skills") not in target.parents:
            continue
        if not target.exists():
            clear(p)
            print(f"Pruned {p} -> {target} (skill no longer exists)")


def materialize_env() -> int:
    if shutil.which("pixi") is None:
        print(
            "error: pixi is not on PATH. This repo is pixi-managed; install",
            file=sys.stderr,
        )
        print("       pixi from https://pixi.sh and re-run.", file=sys.stderr)
        return 1
    print("Materializing dev environment (pixi install -e dev)...")
    result = subprocess.run(
        ["pixi", "install", "-e", "dev", "--manifest-path", str(REPO / "pixi.toml")],
        check=False,
    )
    return result.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="install under this home instead of ~",
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="do not run pixi install or register hooks",
    )
    args = parser.parse_args(argv)

    claude_dir = args.home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    install_stub(claude_dir)
    problems = install_skills(claude_dir)
    prune(claude_dir)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        return 1

    if args.skip_env:
        return 0

    if (rc := materialize_env()) != 0:
        return rc

    py = platform_paths.interpreter(REPO)
    if not py.exists():
        print(
            f"error: expected {py} after pixi install; aborting rather than",
            file=sys.stderr,
        )
        print("       registering hooks that cannot start.", file=sys.stderr)
        return 1

    return subprocess.run(
        [str(py), str(REPO / "scripts" / "register_hooks.py")],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
