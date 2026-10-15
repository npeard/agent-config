#!/usr/bin/env python
"""Flag functions too thin to justify existing: trivial wrappers, one-use helpers.

CODING_STANDARDS rule 13 and the Lazy Element / Middle Man smells are
judgement calls, and agents keep producing single-statement, single-use
helpers in scripts a reader scans top to bottom. Each is a name the reader
must hold and a jump they must make for no logic gained. This makes the call
mechanical.

Usage:
    python scripts/trivial_wrappers.py [--gate] PATH...

PATH is a ``.py`` file or a directory searched recursively. Prints
``path:line: <kind>: <name> (<n> call sites)`` per finding. Report mode exits
0; ``--gate`` exits 1 on any finding. A file that cannot be read or parsed
fails in both modes, since nothing was checked.

A finding is a module-level or nested function (methods are excluded) that is

- ``trivial-wrapper``: its body, docstring excluded, is one statement -- a
  return, bare expression or assignment -- whose value is a call, attribute,
  constructor, literal or comprehension; or
- ``single-use-helper``: private (``_``-prefixed) or nested, or public in a
  script (a module with an ``if __name__`` block, whose functions have no
  outside callers), and referenced exactly once in its module.

A function that is both reports as a trivial wrapper. A public function
referenced from the ``if __name__ == "__main__":`` block is an entry point
and exempt, as is any decorated function, ``test_*`` function, or stub
(``...`` body, e.g. an ``@overload``). Recursive calls are not uses.
``# wrapper-ok: <reason>`` on the ``def`` line silences a
finding; a marker with no reason is a ``bare-marker`` finding, the same
convention as scripts/suppressions.py.

Deliberately crude, like surface_area.py: call sites are every load of the
bare name anywhere in the module, so a shadowing variable or a same-named
function elsewhere in the file inflates the count.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

MARKER = re.compile(r"#\s*wrapper-ok\b(?P<rest>.*)")

# The value kinds the spec calls trivial. Arithmetic, names and conditionals
# are absent: they are logic, however short.
TRIVIAL_VALUES = (
    ast.Call,
    ast.Attribute,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.JoinedStr,
)

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Finding:
    line: int
    kind: str
    name: str
    call_sites: int


def has_reason(rest: str) -> bool:
    """Whether the text after a marker explains anything."""
    return bool(re.search(r"[A-Za-z]{3}", rest.strip(" -#:")))


def functions(
    node: ast.AST, nested: bool = False
) -> Iterator[tuple[FunctionNode, bool]]:
    """Every non-method function with whether it is nested in another function."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, FunctionNode):
            yield child, nested
            yield from functions(child, True)
        elif isinstance(child, ast.ClassDef):
            # A method is excluded, but a function nested in one is not.
            for method in child.body:
                if isinstance(method, FunctionNode):
                    yield from functions(method, True)
                else:
                    yield from functions(method, nested)
        else:
            yield from functions(child, nested)


def statements(func: FunctionNode) -> list[ast.stmt]:
    """The body without its docstring."""
    body = func.body
    if (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def is_stub(func: FunctionNode) -> bool:
    """A placeholder or @overload signature: no statements, `pass` or `...`."""
    body = statements(func)
    return not body or (
        len(body) == 1
        and (
            isinstance(body[0], ast.Pass)
            or (
                isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and body[0].value.value is Ellipsis
            )
        )
    )


def is_trivial(func: FunctionNode) -> bool:
    body = statements(func)
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Return | ast.Expr | ast.Assign | ast.AnnAssign):
        return isinstance(stmt.value, TRIVIAL_VALUES)
    return False


def is_main_guard(node: ast.stmt) -> bool:
    """Whether ``node`` is ``if __name__ == "__main__":``."""
    if not (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)):
        return False
    test = node.test
    operands = [test.left, *test.comparators]
    return (
        len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and any(isinstance(o, ast.Name) and o.id == "__name__" for o in operands)
        and any(isinstance(o, ast.Constant) and o.value == "__main__" for o in operands)
    )


def check(source: str) -> list[Finding]:
    """Findings for one module's source, in line order."""
    tree = ast.parse(source)
    lines = source.splitlines()
    uses = Counter(
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    )
    is_script = any(is_main_guard(stmt) for stmt in tree.body)
    entry_points = {
        n.id
        for stmt in tree.body
        if is_main_guard(stmt)
        for n in ast.walk(stmt)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    found = []
    for func, nested in functions(tree):
        name = func.name
        # A recursive call is the function using itself, not a caller.
        own = sum(
            isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
            for n in ast.walk(func)
        )
        sites = uses[name] - own
        # The marker may sit on any line of a multi-line signature.
        # The signature may span lines, and a one-line body shares the line
        # its colon is on; either way the marker belongs to the def.
        first = func.body[0]
        shares_line = ":" in lines[first.lineno - 1][: first.col_offset]
        header = lines[func.lineno - 1 : first.lineno - (not shares_line)]
        marker = next(filter(None, map(MARKER.search, header)), None)
        if marker and not has_reason(marker.group("rest")):
            found.append(Finding(func.lineno, "bare-marker", name, sites))
            continue
        # A decorator is a use (registration, fixture, route) and pytest
        # collects test_* by name, so neither has a visible call site.
        if marker or func.decorator_list or name.startswith("test_") or is_stub(func):
            continue
        if not nested and name in entry_points and name[0] != "_":
            continue
        if is_trivial(func):
            found.append(Finding(func.lineno, "trivial-wrapper", name, sites))
        elif (is_script or nested or name.startswith("_")) and sites == 1:
            found.append(Finding(func.lineno, "single-use-helper", name, sites))
    return sorted(found, key=lambda f: f.line)


def python_files(paths: list[str]) -> Iterator[Path]:
    for name in paths:
        path = Path(name)
        yield from sorted(path.rglob("*.py")) if path.is_dir() else [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gate", action="store_true", help="exit 1 on any finding")
    parser.add_argument("paths", nargs="+", help="files or directories to scan")
    args = parser.parse_args(argv)
    total, failed = 0, False
    for path in python_files(args.paths):
        try:
            findings = check(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"{path}: cannot be checked ({exc})", file=sys.stderr)
            failed = True
            continue
        for f in findings:
            print(f"{path}:{f.line}: {f.kind}: {f.name} ({f.call_sites} call sites)")
        total += len(findings)
    return int(failed or (args.gate and total > 0))


if __name__ == "__main__":
    sys.exit(main())
