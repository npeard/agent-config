#!/usr/bin/env python
"""Fail when a LaTeX or Typst document refers forward to a label.

Usage:
    python scripts/check_forward_refs.py FILE [--json]
    python scripts/check_forward_refs.py --containing FILE [--json]

A reader meets the text in order, so a reference to a label defined later
(``see Sec.~\\ref{sec:result}`` in an introduction's roadmap paragraph) asks
them to hold a pointer to something they cannot yet read. Agent drafts
produced these repeatedly; a rewrite that removed them also read better, so
this is a gate rather than a report. Exit 0 when clean, 1 on any violation,
2 when the file cannot be read.

Exempt, because a reader expects to jump there:

- a reference from the body to a label after ``\\appendix`` (Typst: after a
  heading starting "Appendix" or "Appendices", or an ``<appendix>`` label);
- a reference to a ``fig:`` or ``tab:`` label, or to a label inside a figure
  or table, since floats drift from the text that cites them.

Everything else is flagged, including an appendix pointing at a later
appendix. Labels with no definition (citations, another file) are ignored:
this is not a resolver. ``\\input`` and ``\\include`` are followed in order,
so a thesis is checked in reading order.

Deliberately crude, so the verdict is reproducible rather than correct:

- Comments are stripped by regex; a ``%`` inside verbatim text is a comment.
- A Typst float's extent is found by counting parentheses, so an unbalanced
  parenthesis inside its caption misplaces the end.
- The first definition of a duplicated label wins.
- Plain-word forward pointers ("as we show below") are not detected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

LATEX, TYPST = ".tex", ".typ"

FLOAT_PREFIXES = ("fig:", "tab:")
LATEX_FLOATS = frozenset(
    {
        "figure",
        "table",
        "wrapfigure",
        "wraptable",
        "sidewaysfigure",
        "sidewaystable",
        "subfigure",
    }
)
LATEX_TOKEN = re.compile(
    r"\\(?P<boundary>begin|end)\{(?P<env>[^}]*)\}"
    r"|\\label\{(?P<label>[^}]*)\}"
    r"|\\(?:ref|eqref|cref|Cref|autoref)\*?\{(?P<targets>[^}]*)\}"
    r"|\\(?P<appendix>appendix)\b"
    r"|\\(?:input|include)\{(?P<path>[^}]*)\}"
)
TYPST_TOKEN = re.compile(
    r"^=+[ \t]+(?=(?P<heading>[^\n]*))"
    r"|<(?P<label>[A-Za-z_][\w:.-]*)>"
    r"|@(?P<target>[A-Za-z_][\w:-]*(?:\.[\w:-]+)*)"
    r"|#(?P<float>figure|table)\(",
    re.MULTILINE,
)
TYPST_LABEL = re.compile(r"<[^>]*>")
# "Appendix A: Proofs" opens the appendix as surely as a bare "Appendix".
APPENDIX_HEADINGS = ("appendix", "appendices")


@dataclass(frozen=True)
class Event:
    """A label definition or a reference, in reading order."""

    kind: str  # "label" or "ref"
    name: str
    command: str
    file: str
    line: int
    in_float: bool
    in_appendix: bool


def strip_latex_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def strip_typst_comments(text: str) -> str:
    text = re.sub(
        r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), text, flags=re.DOTALL
    )
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def include_target(name: str, directories: tuple[Path, ...]) -> Path | None:
    """The file an \\input or \\include of `name` reads, or None.

    LaTeX resolves against the compile directory (the root file's) and only
    then the including file's, so `directories` comes in that order. Joining
    the name onto each, rather than re-rooting the first result, keeps an
    absolute or out-of-root name from raising. As in LaTeX, `name.tex` is
    tried before the bare name unless it already ends in .tex, so
    \\input{ch1.v2} reads ch1.v2.tex. An empty or root-only name names no
    file and is skipped.
    """
    if PurePath(name).name in ("", ".."):
        return None
    for directory in directories:
        child = directory / name
        tried = (child,) if child.suffix == LATEX else (Path(f"{child}{LATEX}"), child)
        try:
            found = next((c for c in tried if c.is_file()), None)
        except OSError:
            # An unreadable include costs that include, not the whole check.
            continue
        if found:
            return found
    return None


def latex_events(
    path: Path, root: Path, state: dict, visited: set[Path]
) -> list[Event]:
    """Events of `path` and, in place, of every file it includes.

    `visited` collects each file read, so it is both the cycle guard and the
    include closure document_root asks about. A file is read once even if
    included twice; the first definition of a label would win anyway.
    """
    visited.add(path.resolve())
    text = strip_latex_comments(path.read_text(encoding="utf-8"))
    events: list[Event] = []
    for m in LATEX_TOKEN.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        where: dict[str, Any] = {
            "file": str(path),
            "line": line,
            "in_appendix": state["appendix"],
        }
        if m["boundary"]:
            env = m["env"].removesuffix("*")
            if env == "appendices":
                state["appendix"] = m["boundary"] == "begin"
            elif env in LATEX_FLOATS:
                state["floats"] += 1 if m["boundary"] == "begin" else -1
        elif m["appendix"]:
            state["appendix"] = True
        elif m["label"] is not None:
            events.append(
                Event(
                    "label",
                    m["label"].strip(),
                    "",
                    in_float=state["floats"] > 0,
                    **where,
                )
            )
        elif m["targets"] is not None:
            command = m.group().split("{")[0]
            events += [
                Event("ref", t.strip(), command, in_float=False, **where)
                for t in m["targets"].split(",")
            ]
        else:
            child = include_target(m["path"].strip(), (root, path.parent))
            if child and child.resolve() not in visited:
                events += latex_events(child, root, state, visited)
    return events


def typst_float_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in TYPST_TOKEN.finditer(text):
        if not m["float"]:
            continue
        depth, end = 1, m.end()
        while end < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        spans.append((m.start(), end))
    return spans


def typst_events(path: Path) -> list[Event]:
    text = strip_typst_comments(path.read_text(encoding="utf-8"))
    spans = typst_float_spans(text)
    events: list[Event] = []
    appendix = False
    for m in TYPST_TOKEN.finditer(text):
        line = text.count("\n", 0, m.start()) + 1
        if m["heading"] is not None:
            title = TYPST_LABEL.sub("", m["heading"]).strip()
            appendix = appendix or title.lower().startswith(APPENDIX_HEADINGS)
        elif m["label"]:
            appendix = appendix or m["label"] == "appendix"
            pos = m.start()
            in_float = any(
                s <= pos and (pos < e or not text[e:pos].strip()) for s, e in spans
            )
            events.append(
                Event("label", m["label"], "", str(path), line, in_float, appendix)
            )
        elif m["target"]:
            events.append(
                Event("ref", m["target"], "@", str(path), line, False, appendix)
            )
    return events


def walk(path: Path) -> tuple[list[Event], set[Path]]:
    """Events in reading order, and the resolved files they came from."""
    if path.suffix != LATEX:
        return typst_events(path), {path.resolve()}
    visited: set[Path] = set()
    events = latex_events(path, path.parent, {"appendix": False, "floats": 0}, visited)
    return events, visited


def begins_document(path: Path) -> bool:
    # Streamed so a large non-root file is read only as far as it must be.
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            return any("\\begin{document}" in strip_latex_comments(x) for x in lines)
    except OSError:
        return False


def same_file(path: Path) -> str:
    # lower() as well as normcase: macOS is case-insensitive, normcase is not.
    return os.path.normcase(os.path.realpath(path)).lower()


def document_root(edited: Path) -> Path:
    """The .tex whose reading order covers `edited`, else `edited` itself.

    An edited file holding \\begin{document} is its own root. Otherwise the
    candidates are the roots in its directory and each ancestor up to the git
    root, nearest first, and one counts only if its include closure holds the
    file: a sibling document that never includes it says nothing about it.
    """
    if edited.suffix != LATEX or begins_document(edited):
        return edited
    target = same_file(edited)
    for directory in (edited.parent, *edited.parent.parents):
        for candidate in sorted(directory.glob("*.tex")):
            if same_file(candidate) == target or not begins_document(candidate):
                continue
            try:
                closure = {same_file(f) for f in walk(candidate)[1]}
            except (OSError, UnicodeDecodeError):
                continue
            if target in closure:
                return candidate
        if (directory / ".git").exists():
            break
    return edited


def find_violations(path: Path) -> list[dict]:
    events, _ = walk(path)
    defined: dict[str, tuple[int, Event]] = {}
    for index, event in enumerate(events):
        if event.kind == "label":
            defined.setdefault(event.name, (index, event))
    found = []
    for index, ref in enumerate(events):
        if ref.kind != "ref" or ref.name not in defined:
            continue
        def_index, label = defined[ref.name]
        exempt = (
            ref.name.startswith(FLOAT_PREFIXES)
            or label.in_float
            or (label.in_appendix and not ref.in_appendix)
        )
        if def_index > index and not exempt:
            found.append(
                {
                    "file": ref.file,
                    "line": ref.line,
                    "ref": ref.command,
                    "label": ref.name,
                    "defined_file": label.file,
                    "defined_line": label.line,
                }
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "path", nargs="?", help=".tex or .typ file; \\input/\\include are followed"
    )
    target.add_argument(
        "--containing",
        metavar="FILE",
        help="check the document that includes FILE (see document_root)",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    args = parser.parse_args(argv)
    path = Path(args.path or args.containing)
    if path.suffix not in (LATEX, TYPST):
        print(f"{path}: unsupported suffix (want .tex or .typ)", file=sys.stderr)
        return 2
    try:
        if args.containing:
            path = document_root(path)
        found = find_violations(path)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{path}: cannot read ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"root": str(path), "violations": found}, indent=2))
    else:
        for v in found:
            print(
                f"{v['file']}:{v['line']}: {v['ref']} -> {v['label']} "
                f"(defined {v['defined_file']}:{v['defined_line']})"
            )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
