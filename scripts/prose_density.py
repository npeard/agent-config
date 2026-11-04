#!/usr/bin/env python
"""Report how many numbers and code identifiers sit in prose (LaTeX, Typst, Markdown).

Usage:
    python scripts/prose_density.py FILE... [--depth N] [--json]
        [--max-numbers-per-100 X] [--max-identifiers N]

The rule it measures: prose states the claim, a table or figure carries the
value. Per section and overall it reports prose words, numeric literals per
100 prose words, code identifiers in prose, and where the file's numeric
literals sit -- prose, captions, or tables and figure bodies. With a
threshold it exits 1 when any section exceeds it, else 0.

Built on prose_metrics' parser, and as crude, so counts are reproducible
rather than correct:

- Not prose: headings, comments, display math, code and raw blocks, the
  bibliography, Typst ``#let``/``#set``/``#assert`` code, LaTeX ``verbatim``
  and display-math environments. Floats are not prose either but are counted:
  Typst ``#figure``, ``#fig``, ``#table`` and an ``#align`` holding a table;
  LaTeX ``figure``/``table`` environments; Markdown pipe tables. Captions are
  counted apart from the rest of their float.
- A numeric literal is a ``NUMERIC`` match (decimals, exponents, each end of a
  range; ``%`` adds nothing), or one Typst ``#val(...)``/``#fmt(...)`` call,
  which renders as a number. Digits in references, exponents and subscripts
  (``x^2``, ``a_1``) and inside code spans are not numbers.
- A code identifier is a raw span (Typst/Markdown backticks, LaTeX
  ``\\texttt``/``\\verb``), or outside spans and inline math a dotted name
  (``smi.theory.bounds``, ``plot.py``) or a snake_case token.
- ``--depth N`` folds each heading deeper than N into its level-N ancestor,
  so ``--depth 1`` reports top-level sections.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from prose_metrics import (
    HEADINGS,
    LATEX,
    LATEX_LABEL,
    MARKDOWN,
    MD_FENCE,
    NUMERIC,
    TYPST,
    balanced,
    body_of,
    captions_of,
    latex_envs,
    prose_blocks,
    without_refs,
    words,
)

TYPST_FLOAT_CALL = re.compile(r"#(?:figure|fig|table|align)\(")
TYPST_DROPPED_CALL = re.compile(r"#(?:assert|bibliography)\(")
TYPST_RAW_BLOCK = re.compile(r"^[ \t]*(```).*?\1[ \t]*$\n?", re.DOTALL | re.MULTILINE)
TYPST_VALUE_CALL = re.compile(r"#(?:val|fmt)\(")
LATEX_FLOAT = re.compile(
    latex_envs(("figure", "table", "wrapfigure", "wraptable", "subfigure")),
    re.DOTALL,
)
LATEX_DROPPED = re.compile(
    latex_envs(
        (
            "equation",
            "align",
            "gather",
            "multline",
            "eqnarray",
            "verbatim",
            "lstlisting",
            "minted",
            "thebibliography",
        )
    )
    + r"|(?<!\\)\\\[.*?\\\]|\$\$.*?\$\$|\\bibliography\{[^}]*\}",
    re.DOTALL,
)
MD_TABLE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*$\n?)+", re.MULTILINE)
RAW_SPAN = re.compile(r"`[^`\n]+`|\\texttt\{[^}]*\}|\\verb(.).*?\1")
MATH_SPAN = re.compile(r"\$[^$]*\$|\\\(.*?\\\)")
# A letter starts every part, so 3.5 is a number and smi.theory a name.
DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
SNAKE = re.compile(r"\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b")
# Digits in a script (`x^2`, `a_1`) or glued to a letter (`Q1`, `sm_75`) name
# something; they are not values.
SCRIPT_DIGITS = re.compile(r"[\^_]\{?-?\d[\d.]*|(?<=[A-Za-z])\d+")
LABEL = re.compile(r"\s*<[\w:.-]+>\s*$")
VALUE_TOKEN = " 0.5 "
# `columns: 2` and `stroke: 0.5pt` lay a float out; they are not its values.
TYPST_NAMED_ARG = re.compile(r"\b[a-z-]+:[ \t]*(?!\[)[^,\n\[]*")


def heading_level(line: str, kind: str) -> int:
    if kind == TYPST:
        return len(line) - len(line.lstrip("="))
    if kind == MARKDOWN:
        return len(line) - len(line.lstrip("#"))
    command = re.match(r"\s*\\(\w+)", line)
    name = command.group(1) if command else "section"
    return {"chapter": 0, "section": 1, "subsection": 2}.get(name, 3)


def cut_calls(body: str, pattern: re.Pattern[str]) -> tuple[str, list[str]]:
    """`body` with every balanced call matching `pattern` blanked, and the calls."""
    calls: list[str] = []
    while (m := pattern.search(body)) is not None:
        try:
            inner, end = balanced(body, m.end(), "(", ")")
        except ValueError:
            calls.append(body[m.start() :])
            return body[: m.start()], calls
        # A Typst #align that holds no table is layout around prose.
        if m.group(0) == "#align(" and "table(" not in inner:
            body = body[: m.start()] + "#align[" + inner + "]" + body[end:]
            continue
        calls.append(inner)
        body = body[: m.start()] + "\n" + body[end:]
    return body, calls


def split_regions(body: str, kind: str) -> tuple[str, list[str]]:
    """The body with floats and other non-prose cut out, and the floats' text."""
    if kind == TYPST:
        body = TYPST_RAW_BLOCK.sub("\n", body)
        body, _ = cut_calls(body, TYPST_DROPPED_CALL)
        body, floats = cut_calls(body, TYPST_FLOAT_CALL)
        return body, [TYPST_NAMED_ARG.sub(" ", f) for f in floats]
    if kind == LATEX:
        floats = [m.group(0) for m in LATEX_FLOAT.finditer(body)]
        body = LATEX_FLOAT.sub("\n", LATEX_DROPPED.sub("\n", body))
        return body, floats
    body = MD_FENCE.sub("\n", body)
    floats = MD_TABLE.findall(body)
    return MD_TABLE.sub("\n", body), floats


@dataclass(frozen=True)
class Exhibit:
    label: str | None
    kind: Literal["figure", "table"]
    body: str


TYPST_TABLE_CALL = re.compile(r"\btable\(")
TYPST_HEADER_CALL = re.compile(r"table\.header\(")
TYPST_LABEL_AFTER = re.compile(r"[ \t]*\n?[ \t]*<([\w:.-]+)>")


def typst_exhibits(body: str) -> list[Exhibit]:
    body = TYPST_RAW_BLOCK.sub("\n", body)
    found: list[Exhibit] = []
    pos = 0
    while (m := TYPST_FLOAT_CALL.search(body, pos)) is not None:
        try:
            inner, end = balanced(body, m.end(), "(", ")")
        except ValueError:
            return found
        has_table = m.group(0) == "#table(" or TYPST_TABLE_CALL.search(inner)
        # A Typst #align that holds no table is layout around prose.
        if m.group(0) == "#align(" and not has_table:
            pos = m.end()
            continue
        label = TYPST_LABEL_AFTER.match(body, end)
        found.append(
            Exhibit(
                label.group(1) if label else None,
                "table" if has_table else "figure",
                inner,
            )
        )
        pos = end
    return found


def exhibits(text: str, kind: str) -> list[Exhibit]:
    """Every figure and table in the document, in order, with its label if any."""
    body = body_of(text, kind)
    if kind == TYPST:
        return typst_exhibits(body)
    if kind == LATEX:
        return [
            Exhibit(
                label.group(1) if (label := LATEX_LABEL.search(m.group(0))) else None,
                "table" if "table" in m.group(1) else "figure",
                m.group(0),
            )
            for m in LATEX_FLOAT.finditer(body)
        ]
    return [
        Exhibit(None, "table", t) for t in MD_TABLE.findall(MD_FENCE.sub("\n", body))
    ]


TYPST_NAMED_START = re.compile(r"[a-z-]+\s*:")
TYPST_NON_CELL = re.compile(r"\.\.|table\.header\(")


def top_level_args(call_inner: str) -> list[str]:
    """Comma-separated arguments outside any bracket, string or `$...$` math."""
    args, depth, start, i = [], 0, 0, 0
    while i < len(call_inner):
        ch = call_inner[i]
        if ch in '"$':
            i = call_inner.find(ch, i + 1)
            if i == -1:
                break
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(call_inner[start:i])
            start = i + 1
        i += 1
    return [a.strip() for a in [*args, call_inner[start:]] if a.strip()]


def typst_cells(body: str) -> int:
    """Positional `table(...)` arguments that are not the header.

    A spread argument (`..rows`) cannot be counted statically and adds zero.
    """
    call = TYPST_TABLE_CALL.search(body)
    # A bare #table call's body already starts inside the table.
    inner = body if call is None else balanced(body, call.end(), "(", ")")[0]
    return sum(
        not TYPST_NAMED_START.match(a) and not TYPST_NON_CELL.match(a)
        for a in top_level_args(inner)
    )


def table_cells(exhibit: Exhibit, kind: str) -> int:
    """Data cells of a table exhibit; the header row is not data."""
    if exhibit.kind != "table":
        return 0
    if kind == TYPST:
        return typst_cells(exhibit.body)
    if kind == LATEX:
        # Without a \midrule there is no header to drop.
        data = exhibit.body.split("\\midrule", 1)[-1]
        data = re.sub(
            r"\\(?:bottomrule|end\{tabular\*?\}.*)", "", data, flags=re.DOTALL
        )
        rows = [r for r in data.split("\\\\") if "&" in r]
        return sum(r.count("&") + 1 for r in rows)
    rows = exhibit.body.strip().splitlines()[2:]
    return sum(r.strip().strip("|").count("|") + 1 for r in rows)


def with_values_as_numbers(text: str) -> str:
    """`text` with each `#val(...)`/`#fmt(...)` call replaced by one number."""
    while (m := TYPST_VALUE_CALL.search(text)) is not None:
        try:
            _, end = balanced(text, m.end(), "(", ")")
        except ValueError:
            end = len(text)
        text = text[: m.start()] + VALUE_TOKEN + text[end:]
    return text


def count_numbers(text: str) -> int:
    text = RAW_SPAN.sub(" ", with_values_as_numbers(without_refs(text)))
    return len(NUMERIC.findall(SCRIPT_DIGITS.sub(" ", text)))


def count_identifiers(text: str) -> int:
    # LaTeX escapes the underscore that makes a token snake_case.
    text = without_refs(text).replace("\\_", "_")
    spans = len(RAW_SPAN.findall(text))
    text = MATH_SPAN.sub(" ", RAW_SPAN.sub(" ", with_values_as_numbers(text)))
    dotted = len(DOTTED.findall(text))
    return spans + dotted + len(SNAKE.findall(DOTTED.sub(" ", text)))


def density(row: dict[str, Any]) -> dict[str, Any]:
    n = row["words"]
    row["numbers_per_100_words"] = round(100 * row["numbers"] / n, 2) if n else 0.0
    return row


def analyze(text: str, kind: str, depth: int | None) -> dict[str, Any]:
    body = body_of(text, kind)
    caption_numbers = sum(count_numbers(c) for _, c in captions_of(body, kind))
    prose, floats = split_regions(body, kind)
    float_numbers = sum(count_numbers(f) for f in floats) - caption_numbers
    titles, blocks = prose_blocks(prose, kind)
    heading = HEADINGS[kind]
    levels = [0] + [
        heading_level(line, kind) for line in prose.splitlines() if heading.match(line)
    ]
    # Each section's reported owner: itself, or its nearest ancestor at `depth`.
    owner = list(range(len(titles)))
    for i in range(1, len(titles)):
        if depth is not None and levels[i] > depth:
            owner[i] = owner[i - 1]
    rows: dict[int, dict[str, Any]] = {}
    for index, paragraph in blocks:
        n = words(paragraph, kind)
        if not n:
            continue
        key = owner[index]
        row = rows.setdefault(
            key,
            {
                "title": LABEL.sub("", titles[key]),
                "words": 0,
                "numbers": 0,
                "identifiers": 0,
            },
        )
        row["words"] += n
        row["numbers"] += count_numbers(paragraph)
        row["identifiers"] += count_identifiers(paragraph)
    sections = [density(rows[k]) for k in sorted(rows)]
    prose_numbers = sum(r["numbers"] for r in sections)
    total = prose_numbers + caption_numbers + float_numbers
    overall = density(
        {
            "words": sum(r["words"] for r in sections),
            "numbers": prose_numbers,
            "identifiers": sum(r["identifiers"] for r in sections),
            "caption_numbers": caption_numbers,
            "float_numbers": float_numbers,
            "prose_number_share": round(prose_numbers / total, 3) if total else 0.0,
        }
    )
    found = exhibits(text, kind)
    document = {
        "exhibits": len(found),
        "figures": sum(e.kind == "figure" for e in found),
        "tables": sum(e.kind == "table" for e in found),
        "unlabelled": sum(e.label is None for e in found),
        "table_cells": sum(table_cells(e, kind) for e in found),
    }
    return {"sections": sections, "overall": overall, "document": document}


def breaches(
    data: dict[str, Any], max_per_100: float | None, max_ids: int | None
) -> list[str]:
    found = []
    for row in data["sections"]:
        name = row["title"] or "(untitled)"
        if max_per_100 is not None and row["numbers_per_100_words"] > max_per_100:
            found.append(f"{name}: {row['numbers_per_100_words']} numbers per 100")
        if max_ids is not None and row["identifiers"] > max_ids:
            found.append(f"{name}: {row['identifiers']} identifiers")
    return found


def format_report(path: str, data: dict[str, Any]) -> str:
    o, d = data["overall"], data["document"]
    lines = [
        f"{path}",
        f"  {'section':<48} {'words':>6} {'num':>5} {'/100':>6} {'ids':>4}",
        *(
            f"  {(r['title'] or '(untitled)')[:48]:<48} {r['words']:>6} "
            f"{r['numbers']:>5} {r['numbers_per_100_words']:>6} {r['identifiers']:>4}"
            for r in data["sections"]
        ),
        (
            f"  {'overall':<48} {o['words']:>6} {o['numbers']:>5} "
            f"{o['numbers_per_100_words']:>6} {o['identifiers']:>4}"
        ),
        (
            f"  numeric literals: {o['numbers']} prose, "
            f"{o['caption_numbers']} captions, {o['float_numbers']} tables/figures; "
            f"prose share {o['prose_number_share']}"
        ),
        (
            f"  exhibits {d['exhibits']} ({d['figures']} figures, {d['tables']} tables, "
            f"{d['table_cells']} table cells, {d['unlabelled']} unlabelled)"
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help=".tex, .typ or .md files")
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    parser.add_argument(
        "--depth", type=int, help="fold headings deeper than this level into parents"
    )
    parser.add_argument("--max-numbers-per-100", type=float, metavar="X")
    parser.add_argument("--max-identifiers", type=int, metavar="N")
    args = parser.parse_args(argv)
    results: dict[str, Any] = {}
    failed: list[str] = []
    for name in args.paths:
        path = Path(name)
        if path.suffix not in HEADINGS:
            print(
                f"{path}: unsupported suffix (want .tex, .typ or .md)", file=sys.stderr
            )
            return 2
        try:
            data = analyze(path.read_text(encoding="utf-8"), path.suffix, args.depth)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot read ({exc})", file=sys.stderr)
            return 2
        results[name] = data
        failed += [
            f"{name}: {b}"
            for b in breaches(data, args.max_numbers_per_100, args.max_identifiers)
        ]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("\n".join(format_report(k, v) for k, v in results.items()))
    for line in failed:
        print(f"over threshold: {line}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
