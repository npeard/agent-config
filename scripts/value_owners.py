#!/usr/bin/env python
"""List values cited by more than one exhibit (Typst and LaTeX).

Usage:
    python scripts/value_owners.py FILE... [--json] [--values PATH]

A value is cited by key: Typst ``#val("key")``, LaTeX ``\\val{key}``. Each
figure or table, caption included, is one owner of the keys in it; a key
repeated inside one exhibit is still one owner. Prose citations count under
``<prose>`` and an exhibit with no label under ``<unlabelled:N>``. A key
owned by two or more exhibits is reported, most-shared first: the value is
stated twice where one exhibit should carry it. Report only; exit 0 on
findings, 2 on a usage error.

With ``--values PATH`` (a JSON object, key -> rendered value), keys that
render to the same string are one quantity, so a value re-keyed per section
is still found stated in two exhibits. Booleans, non-scalar entries and
values under three significant characters (digits left after dropping "."
and leading zeros) are skipped, as they match by coincidence. Only
quantities spanning more than one key are listed there; a single shared key
is already in the key report. Markdown has no key syntax and is refused.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

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


MIN_SIGNIFICANT = 3


def quantities(
    found: dict[str, list[str]], values: dict[str, object]
) -> list[dict[str, Any]]:
    """Cited keys grouped by rendered value; groups of 2+ keys in 2+ exhibits."""
    groups: dict[str, list[str]] = {}
    for key in found:
        value = values.get(key)
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value)
        if len(text.replace(".", "").lstrip("0")) >= MIN_SIGNIFICANT:
            groups.setdefault(text, []).append(key)
    rows = []
    for text, keys in groups.items():
        labels = list(dict.fromkeys(o for k in keys for o in found[k] if o != PROSE))
        if len(keys) > 1 and len(labels) > 1:
            rows.append({"value": text, "keys": keys, "exhibits": labels})
    return sorted(rows, key=lambda r: -len(r["exhibits"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help=".typ or .tex files")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    parser.add_argument("--values", metavar="PATH", help="JSON of key -> value")
    args = parser.parse_args(argv)
    try:
        values = (
            json.loads(Path(args.values).read_text(encoding="utf-8"))
            if args.values
            else None
        )
    except (OSError, ValueError) as exc:
        print(f"{args.values}: cannot read ({exc})", file=sys.stderr)
        return 2
    if values is not None and not isinstance(values, dict):
        print(f"{args.values}: want a JSON object", file=sys.stderr)
        return 2
    reports: dict[str, tuple[int, dict[str, list[str]], list[dict[str, Any]]]] = {}
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
        quants = quantities(found, values) if values is not None else []
        reports[name] = (len(found), shared(found), quants)
    if args.json:
        out: dict[str, dict[str, object]] = {}
        for name, (_, rows, quants) in reports.items():
            out[name] = dict(rows)
            if values is not None:
                out[name]["quantities"] = quants
        print(json.dumps(out, indent=2))
        return 0
    for name, (total, rows, quants) in reports.items():
        prefix = f"{name}: " if len(reports) > 1 else ""
        for key, labels in rows.items():
            print(f"{prefix}{key}  {len(labels)}  {', '.join(labels)}")
        for q in quants:
            print(
                f"{prefix}value {q['value']}  {len(q['exhibits'])}  "
                f"{', '.join(q['keys'])}  in  {', '.join(q['exhibits'])}"
            )
        print(f"{prefix}{total} keys, {len(rows)} shared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
