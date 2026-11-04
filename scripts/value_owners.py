#!/usr/bin/env python
"""List values cited by more than one exhibit (Typst and LaTeX).

Usage:
    python scripts/value_owners.py FILE... [--json]

A value is cited by key: Typst ``#val("key")``, LaTeX ``\\val{key}``. Each
figure or table, caption included, is one owner of the keys in it; a key
repeated inside one exhibit is still one owner. Prose citations count under
``<prose>`` and an exhibit with no label under ``<unlabelled:N>``. A key
owned by two or more exhibits is reported, most-shared first: the value is
stated twice where one exhibit should carry it. Report only; exit 0 on
findings, 2 on a usage error. Markdown has no key syntax and is refused.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from prose_density import exhibits, split_regions
from prose_metrics import LATEX, TYPST, body_of

KEY = {
    TYPST: re.compile(r"\bval\(\s*\"([^\"]+)\""),
    LATEX: re.compile(r"\\val\{([^}]+)\}"),
}
PROSE = "<prose>"


def owners(text: str, kind: str) -> dict[str, list[str]]:
    """Value key -> ordered unique owners: exhibit labels, then `<prose>`."""
    found: dict[str, list[str]] = {}
    unlabelled = 0
    for exhibit in exhibits(text, kind):
        label = exhibit.label
        if label is None:
            unlabelled += 1
            label = f"<unlabelled:{unlabelled}>"
        for key in KEY[kind].findall(exhibit.body):
            if label not in found.setdefault(key, []):
                found[key].append(label)
    prose, _ = split_regions(body_of(text, kind), kind)
    for key in KEY[kind].findall(prose):
        if PROSE not in found.setdefault(key, []):
            found[key].append(PROSE)
    return found


def shared(found: dict[str, list[str]]) -> dict[str, list[str]]:
    """Keys with more than one exhibit owner, most-owned first."""
    counts = {k: [o for o in v if o != PROSE] for k, v in found.items()}
    keys = sorted(
        (k for k, v in counts.items() if len(v) > 1), key=lambda k: -len(counts[k])
    )
    return {k: found[k] for k in keys}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help=".typ or .tex files")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    args = parser.parse_args(argv)
    reports: dict[str, tuple[int, dict[str, list[str]]]] = {}
    for name in args.paths:
        path = Path(name)
        if path.suffix not in KEY:
            print(
                f"{path}: not supported (want .tex or .typ; Markdown has no value keys)",
                file=sys.stderr,
            )
            return 2
        try:
            found = owners(path.read_text(encoding="utf-8"), path.suffix)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot read ({exc})", file=sys.stderr)
            return 2
        reports[name] = (len(found), shared(found))
    if args.json:
        print(json.dumps({k: v[1] for k, v in reports.items()}, indent=2))
        return 0
    for name, (total, rows) in reports.items():
        prefix = f"{name}: " if len(reports) > 1 else ""
        for key, labels in rows.items():
            print(f"{prefix}{key}  {len(labels)}  {', '.join(labels)}")
        print(f"{prefix}{total} keys, {len(rows)} shared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
