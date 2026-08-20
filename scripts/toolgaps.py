#!/usr/bin/env python
"""Report idiomatic tooling a project is missing, and assets that could fill it.

Boundary with preflight.py, kept deliberately sharp because the two were
nearly duplicates: **preflight asks whether this repo is fit to work in
right now (state); toolgaps asks whether the project has the tooling it
should have at all (capability).** So preflight owns pre-commit
installation and test results, and this script does not check either.

Absent tooling produces no error, so it never appears in a friction report
however long you wait -- a missing formatter or type checker is invisible
until something looks for it on purpose. That is what this is for.

It reports and never fixes: adopting a type checker into a project has real
consequences for its CI and its authors, so the decision is not automatic.

Assumes a current interpreter, supplied by the project's local pixi
environment rather than by whatever `python3` is on PATH. preflight owns
checking that assumption; duplicating it here would put one concept in two
places.

Usage:
    python scripts/toolgaps.py [--json] [--no-assets]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Where cross-project tooling lives, by this setup's convention. Absent on a
# machine that has not cloned it, which is not an error.
CLAUDE_CONFIG = Path.home() / "Documents" / "Projects" / "claude-config"

# Capability -> substrings that evidence it. Matched against a blob built
# from filenames, pre-commit hook ids, and task/dependency names, so one
# table covers several ecosystems without needing to detect which is in use.
CAPABILITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "formatter",
        (
            "ruff-format",
            "ruff format",
            "black",
            "prettier",
            "mdformat",
            "gofmt",
            "rustfmt",
            "clang-format",
        ),
    ),
    (
        "linter",
        ("ruff", "flake8", "pylint", "eslint", "clippy", "golangci", "shellcheck"),
    ),
    ("type checker", ("mypy", "pyright", "basedpyright", "tsc", "typescript", "flow")),
    ("spell check", ("codespell", "cspell", "typos")),
    (
        "dependency lock",
        (
            "pixi.lock",
            "poetry.lock",
            "uv.lock",
            "Cargo.lock",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "go.sum",
        ),
    ),
    (
        "ci",
        (
            ".github/workflows",
            ".gitlab-ci.yml",
            "azure-pipelines",
            "Jenkinsfile",
            ".circleci",
            ".travis.yml",
        ),
    ),
    ("editorconfig", (".editorconfig",)),
)


def repo_root() -> Path:
    """The repository root, not the current directory.

    Run from a subdirectory, a cwd-based scan finds none of the root's
    config files and reports every capability absent -- a wrong answer
    rather than a degraded one, and one that feeds `reflect` straight into
    proposing tools the project already has.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()
    return Path(out.stdout.strip() or ".")


def evidence(root: Path) -> str:
    """A searchable blob of what this project declares about its tooling.

    Filenames alone miss tools configured inside pyproject.toml or declared
    only as a pre-commit hook, so file *contents* of the usual declaration
    files are included rather than just their names.
    """
    parts: list[str] = []
    try:
        parts.extend(p.name for p in root.iterdir())
    except OSError:
        return ""
    if (root / ".github" / "workflows").is_dir():
        parts.append(".github/workflows")
    for name in (
        ".pre-commit-config.yaml",
        "pixi.toml",
        "pyproject.toml",
        "package.json",
        "Taskfile.yml",
        "setup.cfg",
        "tox.ini",
        "Makefile",
        "ruff.toml",
        ".mdformat.toml",
        "Cargo.toml",
        "go.mod",
    ):
        path = root / name
        if path.is_file():
            try:
                parts.append(path.read_text(errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def matches(needle: str, blob: str) -> bool:
    """Whether the blob evidences this needle.

    Bare words are matched on word boundaries, not as substrings: "flow"
    otherwise matches "workflow" and reports a type checker that does not
    exist. Needles containing punctuation are filenames or flags, specific
    enough to match plainly -- and `\b` behaves badly next to a leading dot.
    """
    needle = needle.lower()
    if needle.isalnum():
        return re.search(rf"\b{re.escape(needle)}\b", blob) is not None
    return needle in blob


def gaps(root: Path) -> list[tuple[str, str]]:
    """(capability, evidence-found-or-empty) for each capability, in order."""
    blob = evidence(root).lower()
    out = []
    for name, needles in CAPABILITIES:
        hits = [n for n in needles if matches(n, blob)]
        out.append((name, ", ".join(hits[:3])))
    return out


def assets(config: Path = CLAUDE_CONFIG) -> dict[str, list[str]]:
    """Reusable tooling already available to copy or adapt.

    This is what makes "an asset already solves this, it just is not
    installed here" a reachable conclusion; without the inventory there is
    no reason to look.
    """
    if not config.is_dir():
        return {}
    found: dict[str, list[str]] = {}
    for label, pattern in (
        ("scripts", "scripts/*.py"),
        ("hooks", "hooks/*.py"),
        ("skills", "skills/*/SKILL.md"),
    ):
        names = sorted(
            p.parent.name if label == "skills" else p.name for p in config.glob(pattern)
        )
        if names:
            found[label] = names
    return found


def render(root: Path, show_assets: bool) -> None:
    rows = gaps(root)
    width = max(len(n) for n, _ in rows)
    missing = 0
    for name, found in rows:
        if found:
            print(f"[ok ] {name:<{width}}  {found}")
        else:
            print(f"[GAP] {name:<{width}}  none found")
            missing += 1
    print(f"\n{len(rows) - missing}/{len(rows)} capabilities present")
    if missing:
        print("Absent tooling never shows up as friction; it produces no error.")

    if not show_assets:
        return
    inventory = assets()
    if not inventory:
        return
    print("\nAvailable in claude-config to copy or adapt:")
    for label, names in inventory.items():
        print(f"  {label:8} {', '.join(names)}")
    print("Prefer adapting one of these over writing something new; if more")
    print("than one looks relevant, check whether they duplicate a concept.")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable")
    parser.add_argument(
        "--no-assets", action="store_true", help="skip the claude-config inventory"
    )
    args = parser.parse_args(argv)

    root = repo_root()
    if args.json:
        rows = gaps(root)
        print(
            json.dumps(
                {
                    "present": {n: f for n, f in rows if f},
                    "gaps": [n for n, f in rows if not f],
                    # Honour --no-assets here too: a caller passing it is
                    # asking us not to touch claude-config at all.
                    "assets": {} if args.no_assets else assets(),
                }
            )
        )
    else:
        render(root, show_assets=not args.no_assets)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
