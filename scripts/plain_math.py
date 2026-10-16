#!/usr/bin/env python
r"""Flag ASCII stand-ins for math in figure text and document prose.

A phase diagram titled "mean |<kappa_b>|", ticked "pi/2 ... 3pi/2" or
annotated "+phi" ships uncompiled notation beside a document that typesets
the same symbols properly. A label string compiles either way, so nothing
caught it and agents kept writing it; this makes the rule mechanical.

Usage:
    python scripts/plain_math.py [--gate] PATH...

PATH is a file, a directory searched recursively, or a glob (expanded here,
since Windows shells do not). Prints
``path:line:col: kind: "token" -> suggestion`` per finding. Report mode exits
0; ``--gate`` exits 1 on any finding. A file that cannot be read or parsed
fails in both modes, since nothing was checked.

What is read:

- ``.typ`` -- markup outside math, raw, comments, labels and references, plus
  the string value of a ``title:``, ``subtitle:`` or ``caption:`` argument.
  Other code (``#let``, ``#set``, call arguments) is skipped: a path or a key
  there is not prose.
- ``.tex`` -- the body after ``\begin{document}`` outside math and
  verbatim-like environments; arguments of ``\label``, ``\ref``,
  ``\cite``, ``\includegraphics`` and similar are skipped.
- ``.py`` -- only a module that imports matplotlib or calls an Axes method.
  String literals passed to a label call (``set_xlabel``, ``set_title``,
  ``text``, ``annotate``, ``legend``, ``set_xticks(labels=...)``, ...) or as
  ``label=``/``labels=``/``title=`` anywhere, outside ``$...$`` mathtext. A
  variable at such a call site is traced, one module deep, to the literals
  assigned to it, looped over or appended to it: labels are often built in a
  list of tuples first.

Kinds: ``greek`` (a spelled letter name as a whole word), ``pi-multiple``
(``2pi``, ``3pi/2``, ``pi/4``), ``magnitude`` (``|x|``), ``expectation``
(``<x>``), ``subscript``/``superscript`` (``J_1``, ``kappa_b``, ``x^2``),
``digit-subscript`` (``J1``, ``E0``), ``function`` (``exp(``, ``arg(``).

``math-ok: <reason>`` in a comment on the finding's line silences it (for a
Python literal, any line of the literal or of its call); a marker with no
reason is a ``bare-marker`` finding, the convention of scripts/suppressions.py.

A project gates on it by copying this file to its scripts/ and adding a local
pre-commit hook; widen ``files`` to wherever its figure scripts live (a .py
that never plots is skipped either way)::

    -   id: plain-math
        name: math is typeset, not spelled, in prose and figure labels
        entry: pixi run python scripts/plain_math.py --gate
        language: system
        files: '(\.typ|(?<!\.code)\.tex|/(figures|plots?)/[^/]*\.py)$'
"""

from __future__ import annotations

import argparse
import ast
import glob
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

GREEK = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "varpi",
    "rho",
    "varrho",
    "sigma",
    "varsigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
    "Gamma",
    "Delta",
    "Theta",
    "Lambda",
    "Xi",
    "Pi",
    "Sigma",
    "Upsilon",
    "Phi",
    "Psi",
    "Omega",
]
_G = "|".join(sorted(GREEK, key=len, reverse=True))

# Alternation order is precedence at one start position: "pi/4" is a
# pi-multiple before it is a Greek word, "kappa_b" a subscript before either.
STAND_IN = re.compile(
    rf"""
    (?P<magnitude>\|(?=[^\s|])[^|\n]{{1,40}}?(?<=[^\s|])\|)
  | (?P<expectation><(?=[A-Za-z\\])[^<>\n]{{1,30}}?(?<=\S)>)
  | (?P<pi_multiple>(?<![\w\\.])
      (?:\d+(?:\.\d+)?\s*pi(?:\s*/\s*\d+)?|pi\s*/\s*\d+)(?!\w))
  | (?P<subscript>(?<![\w\\])(?:{_G}|[A-Za-z])\\?_
      (?:\{{[^{{}}\n]{{1,20}}\}}|[A-Za-z0-9]+))
  | (?P<superscript>(?<![\w\\])(?:{_G}|[A-Za-z]|\d+)\^
      (?:\{{[^{{}}\n]{{1,20}}\}}|[-+]?[A-Za-z0-9]+))
  | (?P<function>(?<![\w\\])(?:exp|arg|Re|Im)\()
  | (?P<greek>(?<![\w\\])(?:{_G})\d*(?!\w))
  | (?P<digit_subscript>(?<![\w\\.])[A-Za-z]\d{{1,2}}(?!\w|\.\d))
    """,
    re.VERBOSE,
)
# "Fig. S1", "Table A2", "step 3a" number things; they are not subscripts.
NUMBERING_WORD = re.compile(
    r"(?i)\b(?:figs?|figures?|tables?|tab|secs?|sections?|eqs?|equations?|"
    r"appendix|app|chapters?|ch|panels?|steps?|phases?|version|rev|items?|"
    r"cases?|parts?|refs?|supplementary|runs?|tests?|rows?|columns?|cols?)"
    r"\.?[~\s]*$"
)
# Terms of art where the letter name is the English word, not the symbol.
ENGLISH = re.compile(
    r"(?i)\b(?:machine\s+epsilon|alpha\s+particles?|beta\s+decay|gamma\s+rays?|"
    r"delta\s+functions?)\b"
)
MARKER = re.compile(r"math-ok\b(?P<rest>.*)")
WORD_RUN = re.compile(r"(?<![\\A-Za-z.])[A-Za-z]{3,}(?: +[A-Za-z]{3,})*(?![A-Za-z])")
GREEK_WORD = re.compile(rf"(?<![A-Za-z\\])({_G})(?![A-Za-z])")
INDEXED = re.compile(rf"(?<![\w\\])({_G}|[A-Za-z])(\d{{1,2}})(?!\w)")
ANGLE = re.compile(r"<([^<>]+)>")
FUNCTION = re.compile(r"(?<![\w\\])(exp|arg|Re|Im)\(")
MATHTEXT = re.compile(r"(?<!\\)\$.*?(?<!\\)\$", re.DOTALL)


@dataclass(frozen=True)
class Finding:
    line: int
    col: int
    kind: str
    token: str
    suggestion: str


def has_reason(rest: str) -> bool:
    """Whether the text after a marker explains anything."""
    return bool(re.search(r"[A-Za-z]{3}", rest.strip(" -#%/:")))


def upright(run: re.Match, typst: bool) -> str:
    """A run of words as upright text in math; Greek names stay symbols."""
    out, words = [], []
    for word in [*run.group().split(), None]:
        if word is None or word in GREEK or word in ("exp", "arg"):
            if words:
                text = '"' + " ".join(words) + '"'
                if not typst:
                    text = "\\mathrm{" + "\\ ".join(words) + "}"
                out.append(text)
                words = []
            if word:
                out.append(word)
        else:
            words.append(word)
    return " ".join(out)


def suggest(token: str, typst: bool) -> str:
    """The token as math: LaTeX/mathtext, or Typst when ``typst``."""
    t = token.replace("\\_", "_")
    t = WORD_RUN.sub(lambda m: upright(m, typst), t)
    t = INDEXED.sub(
        lambda m: f"{m[1]}_{m[2]}" if len(m[2]) == 1 or typst else f"{m[1]}_{{{m[2]}}}",
        t,
    )
    if typst:
        t = ANGLE.sub(lambda m: f"chevron.l {m[1].strip()} chevron.r", t)
        t = GREEK_WORD.sub(
            lambda m: m[1][3:] + ".alt" if m[1].startswith("var") else m[1], t
        )
        t = t.replace("{", "(").replace("}", ")")
    else:
        t = ANGLE.sub(lambda m: f"\\langle {m[1].strip()} \\rangle", t)
        t = GREEK_WORD.sub(lambda m: "\\" + m[1], t)
        t = re.sub(r"([_^])(\\mathrm\{[^}]*\})", r"\1{\2}", t)
        t = FUNCTION.sub(
            lambda m: ("\\mathrm{%s}(" if m[1] in ("Re", "Im") else "\\%s(") % m[1], t
        )
    return f"${t}$"


def stand_ins(text: str, typst: bool) -> Iterator[tuple[int, str, str, str]]:
    """(offset, kind, token, suggestion) for each stand-in in ``text``."""
    english = [m.span() for m in ENGLISH.finditer(text)]
    for m in STAND_IN.finditer(text):
        kind = m.lastgroup
        if any(a <= m.start() < b for a, b in english):
            continue
        if kind == "digit_subscript" and NUMBERING_WORD.search(
            text[max(0, m.start() - 24) : m.start()]
        ):
            continue
        token = m.group().strip()
        yield m.start(), kind.replace("_", "-"), token, suggest(token, typst)


def scan_masked(source: str, visible: bytearray, typst: bool) -> list[Finding]:
    """Findings in the visible characters of ``source``, line by line."""
    masked = "".join(
        c if v or c == "\n" else " " for c, v in zip(source, visible, strict=True)
    )
    found = []
    for number, (line, raw) in enumerate(
        zip(masked.splitlines(), source.splitlines(), strict=True), 1
    ):
        marker = MARKER.search(raw)
        if marker and not has_reason(marker.group("rest")):
            found.append(
                Finding(number, marker.start() + 1, "bare-marker", "math-ok", "")
            )
        if marker:
            continue
        for offset, kind, token, suggestion in stand_ins(line, typst):
            found.append(Finding(number, offset + 1, kind, token, suggestion))
    return found


# --- Typst -----------------------------------------------------------------

IDENT = re.compile(r"[A-Za-z_][\w-]*")
TYPST_LABEL = re.compile(r"<[\w.:-]+>")
TYPST_REF = re.compile(r"@[\w.:-]+")
TYPST_STATEMENTS = {
    "let",
    "set",
    "show",
    "import",
    "include",
    "if",
    "for",
    "while",
    "context",
    "return",
}
# Named arguments whose string value is set as text, unlike a path or key.
CONTENT_KEYS = re.compile(r"\b(?:title|subtitle|caption)\s*:\s*$")


def _skip_comment(s: str, i: int) -> int | None:
    """The end of a comment starting at ``i``, or None if there is none."""
    if s.startswith("//", i):
        end = s.find("\n", i)
        return len(s) if end == -1 else end
    if s.startswith("/*", i):
        end = s.find("*/", i + 2)
        return len(s) if end == -1 else end + 2
    return None


def _until(s: str, i: int, close: str) -> int:
    """Index after the next unescaped ``close`` at or after ``i``."""
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == close:
            return i + 1
        i += 1
    return len(s)


def _raw_end(s: str, i: int) -> int:
    ticks = len(s[i:]) - len(s[i:].lstrip("`"))
    end = s.find("`" * ticks, i + ticks)
    return len(s) if end == -1 else end + ticks


def _typst_hash_at(s: str, i: int, vis: bytearray) -> int | None:
    """Skip the ``#`` construct at ``i``; None if it is a bare ``#``."""
    if m := IDENT.match(s, i + 1):
        return typst_hash(s, m, vis)
    nxt = s[i + 1 : i + 2]
    if nxt == "[":
        return typst_markup(s, i + 2, vis, "]")
    if nxt in ("(", "{"):
        return typst_code(s, i + 2, vis, ")}"["({".index(nxt)], eol=False)
    return None


def typst_markup(s: str, i: int, vis: bytearray, close: str | None) -> int:
    """Mark markup text visible from ``i`` until ``close``; returns the end."""
    while i < len(s):
        c = s[i]
        if close and c == close:
            return i + 1
        # The `//` of a URL, after its scheme's colon, is not a comment.
        end = None if s[i - 1 : i] == ":" else _skip_comment(s, i)
        if end is not None:
            i = end
        elif c == "\\":
            # The escaped character renders literally; a `\_` stays visible
            # whole, since "J\_1" is still a stand-in.
            vis[i : i + 2] = b"\x01\x01" if s[i + 1 : i + 2] == "_" else b"\x00\x01"
            i += 2
        elif c == "`":
            i = _raw_end(s, i)
        elif c == "$":
            i = _until(s, i + 1, "$")
        elif (c == "<" and (m := TYPST_LABEL.match(s, i))) or (
            c == "@" and (m := TYPST_REF.match(s, i))
        ):
            i = m.end()
        elif c == "#" and (end := _typst_hash_at(s, i, vis)) is not None:
            i = end
        elif c == "[" and close == "]":
            i = typst_markup(s, i + 1, vis, "]")
        else:
            vis[i] = 1
            i += 1
    return i


def typst_hash(s: str, m: re.Match, vis: bytearray) -> int:
    """Skip a ``#name...`` expression, keeping the markup of its content blocks."""
    i = m.end()
    if m.group() in TYPST_STATEMENTS:
        return typst_code(s, i, vis, None, eol=True)
    while i < len(s):
        if s[i] == "." and (field := IDENT.match(s, i + 1)):
            i = field.end()
        elif s[i] == "(":
            i = typst_code(s, i + 1, vis, ")", eol=False)
        elif s[i] == "[":
            i = typst_markup(s, i + 1, vis, "]")
        else:
            break
    return i


def typst_code(s: str, i: int, vis: bytearray, close: str | None, *, eol: bool) -> int:
    """Skip code until ``close`` (or a top-level newline when ``eol``)."""
    while i < len(s):
        c = s[i]
        if c == close or (eol and c == "\n"):
            return i + 1
        end = _skip_comment(s, i)
        if end is not None:
            i = end
        elif c == '"':
            end = _until(s, i + 1, '"')
            if CONTENT_KEYS.search(s[max(0, i - 40) : i]):
                vis[i + 1 : end - 1] = b"\x01" * (end - 1 - (i + 1))
            i = end
        elif c == "$":
            i = _until(s, i + 1, "$")
        elif c == "[":
            i = typst_markup(s, i + 1, vis, "]")
        elif c in "({":
            i = typst_code(s, i + 1, vis, ")}"["({".index(c)], eol=False)
        elif c in ")}]":
            # Not ours: a `#if ... [x]]` ends inside its caller's content
            # block, which must see the bracket to close.
            return i
        else:
            i += 1
    return i


def check_typst(source: str) -> list[Finding]:
    vis = bytearray(len(source))
    typst_markup(source, 0, vis, None)
    return scan_masked(source, vis, typst=True)


# --- LaTeX -----------------------------------------------------------------

CONTROL_WORD = re.compile(r"[A-Za-z]+\*?")
MATH_ENVS = {
    "equation",
    "align",
    "alignat",
    "flalign",
    "gather",
    "multline",
    "eqnarray",
    "math",
    "displaymath",
    "dmath",
}
# Code or drawing environments: their text is not prose, and reading tikz
# coordinates or circuit gates as prose is all false positives.
OPAQUE_ENVS = {
    "verbatim",
    "Verbatim",
    "lstlisting",
    "minted",
    "comment",
    "tikzpicture",
    "tikzcd",
    "quantikz",
    "filecontents",
}
# Column specs, which use `|` for rules.
TABULAR_ENVS = {"tabular": 1, "tabularx": 2, "tabular*": 2, "longtable": 1}
# Commands whose first N arguments are keys, paths, lengths or definitions.
SKIP_ARGS = {
    **dict.fromkeys(
        [
            "label",
            "ref",
            "eqref",
            "cref",
            "Cref",
            "autoref",
            "pageref",
            "nameref",
            "cite",
            "citep",
            "citet",
            "citealp",
            "citeauthor",
            "citeyear",
            "nocite",
            "includegraphics",
            "input",
            "include",
            "usepackage",
            "documentclass",
            "bibliography",
            "bibliographystyle",
            "url",
            "href",
            "hypersetup",
            "graphicspath",
            "color",
            "textcolor",
            "pagecolor",
            "hspace",
            "vspace",
            "bibitem",
            "texttt",
            "lstinline",
            "lstinputlisting",
            "ensuremath",
        ],
        1,
    ),
    **dict.fromkeys(
        [
            "newcommand",
            "renewcommand",
            "providecommand",
            "DeclareMathOperator",
            "setlength",
            "addtolength",
            "setcounter",
            "addtocounter",
            "SI",
            "qty",
        ],
        2,
    ),
    **dict.fromkeys(["newenvironment", "renewenvironment", "definecolor"], 3),
}


def _group_end(s: str, i: int, open_: str, close: str) -> int:
    """Index after the group opening at ``i``, nesting balanced."""
    depth = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        depth += (s[i] == open_) - (s[i] == close)
        i += 1
        if depth == 0:
            return i
    return len(s)


def _skip_args(s: str, i: int, count: int) -> int:
    """Index after ``count`` mandatory arguments and any optional ones."""
    while count:
        while i < len(s) and s[i] in " \t\n":
            i += 1
        if s.startswith("[", i):
            i = _group_end(s, i, "[", "]")
        elif s.startswith("{", i):
            i, count = _group_end(s, i, "{", "}"), count - 1
        elif s.startswith("\\", i) and (m := CONTROL_WORD.match(s, i + 1)):
            i, count = m.end(), count - 1
        else:
            i, count = i + 1, count - 1
    return i


def check_latex(source: str) -> list[Finding]:
    vis = bytearray(len(source))
    s = source
    i = max(s.find("\\begin{document}"), 0)
    while i < len(s):
        c = s[i]
        if c == "%":
            end = s.find("\n", i)
            i = len(s) if end == -1 else end
        elif c == "$":
            if s.startswith("$$", i):
                end = s.find("$$", i + 2)
                i = len(s) if end == -1 else end + 2
            else:
                i = _until(s, i + 1, "$")
        elif c == "\\" and s[i + 1 : i + 2] in ("(", "["):
            end = s.find("\\" + ")]"["([".index(s[i + 1])], i + 2)
            i = len(s) if end == -1 else end + 2
        elif c == "\\" and (m := CONTROL_WORD.match(s, i + 1)):
            i = latex_command(s, m, vis)
        elif c == "\\":
            # "J\_1" is a stand-in; any other control symbol is not text.
            vis[i : i + 2] = b"\x01\x01" if s[i + 1 : i + 2] == "_" else b"\0\0"
            i += 2
        else:
            vis[i] = c not in "{}"
            i += 1
    return scan_masked(source, vis, typst=False)


def latex_command(s: str, m: re.Match, vis: bytearray) -> int:
    """Skip a control word and whatever of its arguments is not prose."""
    name, i = m.group(), m.end()
    if name in ("begin", "end"):
        env_end = _skip_args(s, i, 1)
        env = s[i:env_end].strip(" {}\n")
        if name == "begin" and env.rstrip("*") in MATH_ENVS | OPAQUE_ENVS:
            close = s.find("\\end{" + env + "}", env_end)
            return len(s) if close == -1 else close + len("\\end{" + env + "}")
        return _skip_args(
            s, env_end, TABULAR_ENVS.get(env, 0) if name == "begin" else 0
        )
    if name == "verb":
        end = s.find(s[i], i + 1) if i < len(s) else -1
        return len(s) if end == -1 else end + 1
    if name == "def":
        return _skip_args(s, s.find("{", i) if "{" in s[i:] else i, 1)
    return _skip_args(s, i, SKIP_ARGS.get(name.rstrip("*"), 0))


# --- Python figure scripts -------------------------------------------------

LABEL_CALLS = {
    "set_xlabel",
    "set_ylabel",
    "set_zlabel",
    "set_title",
    "suptitle",
    "supxlabel",
    "supylabel",
    "xlabel",
    "ylabel",
    "title",
    "text",
    "figtext",
    "annotate",
    "legend",
    "set_label",
    "set_text",
    "set_xticklabels",
    "set_yticklabels",
    "set_zticklabels",
    "set_xticks",
    "set_yticks",
    "set_zticks",
    "xticks",
    "yticks",
    "set_thetagrids",
    "set_rgrids",
    "bar_label",
}
LABEL_KWARGS = {"label", "labels", "title", "xlabel", "ylabel", "zlabel", "text"}
# Calls only a plotting module makes; `title`/`text` alone are too common.
AXES_CALLS = (LABEL_CALLS - {"title", "text", "set_text", "set_label"}) | {"colorbar"}
MAX_DEPTH = 8


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


Table = dict[str, list[tuple[ast.expr, tuple[int, ...]]]]


def _string_parts(expr: ast.expr) -> list[ast.expr]:
    """The sub-expressions whose strings ``expr`` is built from."""
    match expr:
        case (
            ast.JoinedStr(values=parts)
            | ast.Tuple(elts=parts)
            | ast.List(elts=parts)
            | ast.Set(elts=parts)
        ):
            return parts
        case ast.IfExp():
            return [expr.body, expr.orelse]
        case ast.BinOp():
            return [expr.left, expr.right]
        case ast.Starred():
            return [expr.value]
        case ast.Call(func=ast.Attribute() as func):
            # "...".format(...) and "\n".join([...]) build a label from parts.
            return [func.value, *(expr.args if func.attr == "join" else ())]
    return []


class Bindings:
    """Where each name in a module may get its value: crude, like
    trivial_wrappers.py's call counting -- every binding of a name anywhere
    counts, so a same-named variable elsewhere adds candidates.
    """

    def __init__(self, tree: ast.Module):
        self.values: Table = defaultdict(list)
        self.loops: Table = defaultdict(list)
        self.appended: dict[str, list[ast.expr]] = defaultdict(list)
        self.returns: dict[str, list[ast.expr]] = defaultdict(list)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._bind(self.values, target, node.value, ())
            elif isinstance(node, ast.AnnAssign | ast.AugAssign) and node.value:
                self._bind(self.values, node.target, node.value, ())
            elif isinstance(node, ast.For | ast.comprehension):
                self._bind(self.loops, node.target, node.iter, ())
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                self.returns[node.name] += [
                    r.value
                    for r in ast.walk(node)
                    if isinstance(r, ast.Return) and r.value is not None
                ]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.attr in ("append", "extend", "insert")
                and node.args
            ):
                value = node.args[-1]
                name = node.func.value.id
                if node.func.attr == "extend":
                    self.values[name].append((value, ()))
                else:
                    self.appended[name].append(value)

    def _bind(
        self, table: Table, target: ast.expr, value: ast.expr, path: tuple[int, ...]
    ):
        if isinstance(target, ast.Name):
            table[target.id].append((value, path))
        elif isinstance(target, ast.Tuple | ast.List):
            for k, element in enumerate(target.elts):
                self._bind(table, element, value, (*path, k))

    def resolve(self, name: str, depth: int) -> Iterator[ast.expr]:
        if depth > MAX_DEPTH:
            return
        for value, path in self.values.get(name, ()):
            yield from self.pick(value, path, depth + 1)
        for iterable, path in self.loops.get(name, ()):
            for element in self.elements(iterable, depth + 1):
                yield from self.pick(element, path, depth + 1)

    def pick(
        self, expr: ast.expr, path: tuple[int, ...], depth: int
    ) -> Iterator[ast.expr]:
        """What sits at ``path`` inside ``expr``'s possible values."""
        if depth > MAX_DEPTH:
            return
        if not path:
            yield expr
        elif isinstance(expr, ast.Tuple | ast.List):
            if path[0] < len(expr.elts):
                yield from self.pick(expr.elts[path[0]], path[1:], depth + 1)
        elif isinstance(expr, ast.Name):
            for value in self.resolve(expr.id, depth + 1):
                yield from self.pick(value, path, depth + 1)
        elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            for value in self.returns.get(expr.func.id, ()):
                yield from self.pick(value, path, depth + 1)

    def elements(self, expr: ast.expr, depth: int) -> Iterator[ast.expr]:
        """The elements iterating over ``expr`` may yield."""
        if depth > MAX_DEPTH:
            return
        if isinstance(expr, ast.Tuple | ast.List | ast.Set):
            for element in expr.elts:
                if isinstance(element, ast.Starred):
                    yield from self.elements(element.value, depth + 1)
                else:
                    yield element
        elif isinstance(expr, ast.Name):
            yield from self.appended.get(expr.id, ())
            for value in self.resolve(expr.id, depth + 1):
                yield from self.elements(value, depth + 1)
        elif isinstance(expr, ast.BinOp):
            yield from self.elements(expr.left, depth + 1)
            yield from self.elements(expr.right, depth + 1)
        elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name):
            yield from self._call_elements(expr.func.id, expr.args, depth + 1)

    def _call_elements(
        self, name: str, args: list[ast.expr], depth: int
    ) -> Iterator[ast.expr]:
        """The elements iterating over ``name(*args)`` may yield."""
        if name == "enumerate" and args:
            for element in self.elements(args[0], depth):
                yield ast.Tuple(elts=[ast.Constant(0), element])
        elif name == "zip":
            columns = [list(self.elements(a, depth)) for a in args]
            for row in zip(*columns, strict=False):
                yield ast.Tuple(elts=list(row))
        elif name in ("list", "tuple", "sorted", "reversed") and args:
            yield from self.elements(args[0], depth)
        else:
            for value in self.returns.get(name, ()):
                yield from self.elements(value, depth)

    def strings(self, expr: ast.expr, depth: int) -> Iterator[ast.Constant]:
        """Every string literal ``expr`` may evaluate to, or be built from."""
        if depth > MAX_DEPTH:
            return
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            yield expr
        elif isinstance(expr, ast.Name):
            for value in self.resolve(expr.id, depth + 1):
                yield from self.strings(value, depth + 1)
        else:
            for part in _string_parts(expr):
                yield from self.strings(part, depth + 1)


def is_plotting(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            a.name.split(".")[0] == "matplotlib" for a in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "matplotlib"
        ):
            return True
        if isinstance(node, ast.Call) and _call_name(node) in AXES_CALLS:
            return True
    return False


def check_python(source: str) -> list[Finding]:
    tree = ast.parse(source)
    if not is_plotting(tree):
        return []
    lines = source.splitlines()
    bindings = Bindings(tree)
    found: dict[tuple[int, int, str], Finding] = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        args = [k.value for k in call.keywords if k.arg in LABEL_KWARGS]
        if _call_name(call) in LABEL_CALLS:
            args += call.args
        for arg in args:
            for literal in bindings.strings(arg, 0):
                spans = range(
                    literal.lineno, (literal.end_lineno or literal.lineno) + 1
                )
                marked = [
                    m
                    for n in {*spans, call.lineno}
                    if (m := MARKER.search(lines[n - 1]))
                ]
                if marked and not has_reason(marked[0].group("rest")):
                    key = (call.lineno, 0, "bare-marker")
                    found[key] = Finding(call.lineno, 1, "bare-marker", "math-ok", "")
                if marked:
                    continue
                text = MATHTEXT.sub(lambda m: " " * len(m.group()), str(literal.value))
                for _, kind, token, suggestion in stand_ins(text, typst=False):
                    key = (literal.lineno, literal.col_offset, token)
                    found[key] = Finding(
                        literal.lineno, literal.col_offset + 1, kind, token, suggestion
                    )
    return sorted(found.values(), key=lambda f: (f.line, f.col))


CHECKERS = {".typ": check_typst, ".tex": check_latex, ".py": check_python}
# Generated output and environments: a finding there is not the author's.
SKIP_DIRS = {".git", ".pixi", ".venv", "node_modules", "__pycache__", "build", "_build"}


def check_file(path: Path) -> list[Finding]:
    """Findings for one file; [] for a suffix this does not read."""
    # A pgf/TikZ library is macro code with no prose in it.
    if path.name.endswith(".code.tex"):
        return []
    checker = CHECKERS.get(path.suffix)
    return checker(path.read_text(encoding="utf-8")) if checker else []


def format_finding(path: Path | str, f: Finding) -> str:
    if f.kind == "bare-marker":
        return f"{path}:{f.line}:{f.col}: bare-marker: math-ok needs a reason"
    return f'{path}:{f.line}:{f.col}: {f.kind}: "{f.token}" -> {f.suggestion}'


def _expand(name: str) -> Iterator[Path]:
    """``name`` itself, or what it matches when it is a glob."""
    if not glob.has_magic(name):
        yield Path(name)
        return
    # Path.glob takes no absolute pattern, so split off the drive and root.
    anchor = Path(name).anchor
    yield from Path(anchor or ".").glob(name[len(anchor) :])


def files(paths: list[str]) -> Iterator[Path]:
    for name in paths:
        for path in sorted(_expand(name)):
            if not path.is_dir():
                yield path
                continue
            for found in sorted(path.rglob("*")):
                rel = found.relative_to(path).parts
                if found.suffix in CHECKERS and not SKIP_DIRS & set(rel[:-1]):
                    yield found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate", action="store_true", help="exit 1 on any finding")
    parser.add_argument("paths", nargs="+", help="files, directories or globs")
    args = parser.parse_args(argv)
    total, failed = 0, False
    for path in files(args.paths):
        try:
            findings = check_file(path)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot be checked ({exc})", file=sys.stderr)
            failed = True
            continue
        for f in findings:
            print(format_finding(path, f))
        total += len(findings)
    return int(failed or (args.gate and total > 0))


if __name__ == "__main__":
    sys.exit(main())
