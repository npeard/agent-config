#!/usr/bin/env python
"""Install agent-config's host adapters. Safe to re-run, on any platform.

Ported from install.sh, which could not run outside a POSIX shell and whose
`ln -s` silently deep-copied on Windows -- printing "Linked ..." for a copy
that would never track another edit. Every link written here is verified
afterwards for that reason.

The ordering below is load-bearing and was arrived at by fixing real
failures: directories, then the instruction adapters, then skill links, then the
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


def _load_installation_contract():
    """Import the required sibling contract without relying on sys.path."""
    spec = importlib.util.spec_from_file_location(
        "installation_contract",
        Path(__file__).resolve().parent / "scripts" / "installation_contract.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


platform_paths = _load_platform_paths()
installation_contract = _load_installation_contract()

REPO = Path(__file__).resolve().parent
GUIDANCE_NAME = installation_contract.GUIDANCE_NAME
CODEX_HEADER = installation_contract.CODEX_HEADER


def canonical_guidance(repo: Path = REPO) -> str:
    return installation_contract.canonical_guidance(repo)


def claude_stub(repo: Path = REPO) -> str:
    return installation_contract.claude_stub(repo)


def codex_snapshot(repo: Path = REPO) -> str:
    return installation_contract.codex_snapshot(repo)


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
    """Make dest free without ever destroying anything irreplaceable.

    A link is ours to remove outright: it holds no content of its own and
    what it points at is untouched. Anything else that exists is somebody's
    real data. install.sh tested `-e` and moved it aside; narrowing that to
    files only meant a directory sitting at ~/.claude/CLAUDE.md or at a
    skill path was recursively deleted with no backup at all.
    """
    if platform_paths.is_link(dest):
        # A junction is removed as a directory, a symlink as a file.
        if dest.is_dir() and not dest.is_symlink():
            dest.rmdir()
        else:
            dest.unlink()
    elif dest.exists():
        back_up(dest)


def install_generated_file(dest: Path, expected: str) -> None:
    """Install one exact generated adapter without overwriting user data."""
    if dest.is_file() and not platform_paths.is_link(dest):
        try:
            if dest.read_text(encoding="utf-8") == expected:
                return
        except UnicodeDecodeError:
            # Unreadable text is still user data; clear() preserves its bytes.
            pass
    clear(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(expected, encoding="utf-8")


def install_instructions(home: Path) -> None:
    """Install the exact Claude and Codex adapters from the canonical source."""
    for dest, expected in installation_contract.instruction_adapters(REPO, home):
        install_generated_file(dest, expected)


def install_link(src: Path, dest: Path) -> str | None:
    """Link dest to src and verify it; return a problem description or None."""
    if (
        platform_paths.verify_link(dest, src)
        and platform_paths.link_target(dest) == src.resolve()
    ):
        return None
    clear(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        platform_paths.link_dir(src, dest)
    except OSError as exc:
        return str(exc)
    # Verified, not trusted: a copy reports success just as loudly.
    if not platform_paths.verify_link(dest, src):
        return "produced a copy rather than a link"
    print(f"Linked {dest} -> {src}")
    return None


def install_skills(installed: Path) -> list[str]:
    """Link every skill this repo carries, and verify each one landed."""
    source = REPO / "skills"
    installed.mkdir(parents=True, exist_ok=True)
    problems = []
    for src in sorted(p for p in source.iterdir() if p.is_dir()):
        if problem := install_link(src, installed / src.name):
            problems.append(f"{src.name}: {problem}")
    return problems


def prune(installed: Path) -> None:
    """Drop links into this repo whose skill is gone.

    A renamed or deleted skill otherwise leaves its link behind, and a stale
    link is offered to every session as a real skill. Only links into this
    repo are pruned: another tool's links, and links from a clone kept
    elsewhere, are not ours to remove.
    """
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

    install_instructions(args.home)
    problems = []
    for installed in installation_contract.skill_destinations(args.home):
        problems.extend(
            f"{installed}: {problem}" for problem in install_skills(installed)
        )
        prune(installed)
    # The one stable path hooks and prose use to find this checkout, wherever
    # it was cloned.
    if problem := install_link(REPO, installation_contract.repo_link(args.home)):
        problems.append(f"{installation_contract.repo_link(args.home)}: {problem}")
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

    # --settings is passed explicitly because each registrar defaults to the
    # real home, which would make --home write hooks outside the home named.
    registrars = (
        ("register_hooks.py", args.home / ".claude" / "settings.json"),
        ("register_codex_hooks.py", args.home / ".codex" / "hooks.json"),
    )
    for registrar, settings in registrars:
        result = subprocess.run(
            [str(py), str(REPO / "scripts" / registrar), "--settings", str(settings)],
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
