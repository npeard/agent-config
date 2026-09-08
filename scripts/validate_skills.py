#!/usr/bin/env python
"""Validate this repository's portable Agent Skills profile.

This is intentionally a validator for the conservative frontmatter subset the
repository authors, not a general YAML parser. Keeping the profile to scalar
standard fields makes it portable without adding a parser dependency merely
to validate seven small metadata blocks.

Usage:
    python scripts/validate_skills.py [SKILLS_DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TOP_LEVEL = re.compile(r"(?P<key>[a-z][a-z0-9-]*):(?:\s*(?P<value>.*))?\Z")
STANDARD_FIELDS = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
LIMITS = {"name": 64, "description": 1024, "compatibility": 500}
BLOCK_MARKERS = frozenset({"|", "|-", "|+", ">", ">-", ">+"})


@dataclass(frozen=True)
class Finding:
    path: Path
    detail: str

    def render(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root.parent)
        except ValueError:
            shown = self.path
        return f"{shown.as_posix()}: {self.detail}"


def frontmatter(path: Path) -> tuple[list[str] | None, list[Finding]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, [Finding(path, f"could not read: {exc}")]
    if not lines or lines[0] != "---":
        return None, [Finding(path, "frontmatter must begin on the first line")]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None, [Finding(path, "frontmatter has no closing --- fence")]
    return lines[1:end], []


def scalar(lines: list[str], start: int, raw: str) -> str:
    """Return a plain or block scalar from the repository's YAML subset."""
    parts = [] if raw in BLOCK_MARKERS else [raw]
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        if line.strip():
            parts.append(line.strip())
    value = " ".join(parts).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def fields(path: Path, lines: list[str]) -> tuple[dict[str, str], list[Finding]]:
    found: dict[str, str] = {}
    problems: list[Finding] = []
    for index, line in enumerate(lines):
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = TOP_LEVEL.fullmatch(line)
        if not match:
            problems.append(Finding(path, f"unsupported top-level YAML: {line!r}"))
            continue
        key = match.group("key")
        if key not in STANDARD_FIELDS:
            problems.append(Finding(path, f"non-standard frontmatter field {key!r}"))
            continue
        if key in found:
            problems.append(Finding(path, f"duplicate frontmatter field {key!r}"))
            continue
        found[key] = scalar(lines, index, (match.group("value") or "").strip())
    return found, problems


def validate_skill(path: Path) -> list[Finding]:
    lines, problems = frontmatter(path)
    if lines is None:
        return problems
    values, field_problems = fields(path, lines)
    problems.extend(field_problems)

    for required in ("name", "description"):
        if not values.get(required):
            problems.append(Finding(path, f"missing non-empty {required!r}"))

    name = values.get("name", "")
    if name and not NAME.fullmatch(name):
        problems.append(
            Finding(
                path,
                "name must contain lowercase letters, digits, and single hyphens only",
            )
        )
    if name and name != path.parent.name:
        problems.append(
            Finding(
                path, f"name {name!r} does not match directory {path.parent.name!r}"
            )
        )

    for key, limit in LIMITS.items():
        value = values.get(key)
        if value is not None and len(value) > limit:
            problems.append(
                Finding(path, f"{key} is {len(value)} characters; maximum is {limit}")
            )
    return problems


def validate(skills_dir: Path) -> list[Finding]:
    if not skills_dir.is_dir():
        return [Finding(skills_dir, "skills directory does not exist")]
    directories = sorted(path for path in skills_dir.iterdir() if path.is_dir())
    if not directories:
        return [Finding(skills_dir, "skills directory contains no skill directories")]
    problems: list[Finding] = []
    for directory in directories:
        path = directory / "SKILL.md"
        if not path.is_file():
            problems.append(
                Finding(path, "every skill directory must contain SKILL.md")
            )
        else:
            problems.extend(validate_skill(path))
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "skills_dir",
        nargs="?",
        type=Path,
        default=REPO_ROOT / "skills",
        help="directory whose immediate child directories are skills",
    )
    skills_dir = parser.parse_args(argv).skills_dir
    problems = validate(skills_dir)
    if problems:
        print(f"Agent Skills validation failed ({len(problems)}):")
        for problem in problems:
            print(f"  {problem.render(skills_dir)}")
        return 1
    count = sum(1 for path in skills_dir.iterdir() if path.is_dir())
    print(f"Agent Skills profile valid ({count} skills).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
