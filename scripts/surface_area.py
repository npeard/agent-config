#!/usr/bin/env python
"""Report how much code surface a branch added to a Python package.

Usage:
    python scripts/surface_area.py --repo PATH --package NAME --base REV
        [--head REV] [--json]

Reports, for head minus base: new modules, new public symbols, new internal
import edges, flagged new modules, and new symbols and edges per 100 net LOC.
Each new module, symbol and edge is a concept a reader must hold whatever its
line count, which a LOC diff does not show. It is a report, not a gate: the
exit code is 0 whatever it finds.

Deliberately crude:

- Revisions are read through ``git archive``, so the repo's working tree and
  checked-out branch are never touched.
- A public symbol is a module-level def, class or assigned name with no
  leading underscore. A literal ``__all__`` replaces that rule, so a package
  re-exporting a name counts it again: it is one more place a reader meets
  it. Otherwise imported names are not symbols.
- An edge is a direct import between two modules of the package, from grimp;
  external packages are ignored.
- A new module is flagged when exactly one module imports it and that is
  not its parent package (a re-export has callers outside the package that
  grimp cannot see), or when it imports a ``_name`` or reads ``x._name``
  for any receiver but ``self`` or ``cls``. No types are inferred, so
  ``other._x`` inside the class that owns ``_x`` is flagged too; each read
  is listed for the reader to judge.
- Net LOC is lines added minus lines deleted in the package's ``.py`` files.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import grimp


def _git(repo: str, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", repo, *args], check=True, capture_output=True
    ).stdout


def _package_path(repo: str, rev: str, package: str) -> str:
    for path in (package, f"src/{package}"):
        probe = ["git", "-C", repo, "cat-file", "-e", f"{rev}:{path}"]
        if subprocess.run(probe, check=False, capture_output=True).returncode == 0:
            return path
    raise SystemExit(f"{package} is neither at the root nor under src/ at {rev}")


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.endswith("__")


def _public_symbols(tree: ast.Module) -> set[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.append(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assigned = [
                n.id
                for target in targets
                for n in ast.walk(target)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
            ]
            names += assigned
            if "__all__" in assigned and node.value is not None:
                try:
                    return set(ast.literal_eval(node.value))
                except ValueError:
                    pass  # A computed __all__ cannot be read; use the names.
    return {name for name in names if not name.startswith("_")}


def _private_reads(tree: ast.Module) -> list[str]:
    lines: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_private(node.attr):
            if not (
                isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")
            ):
                lines.setdefault(f"reads private {ast.unparse(node)}", []).append(
                    node.lineno
                )
        elif isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            for alias in node.names:
                if _is_private(alias.name):
                    text = f"imports private {source}.{alias.name}"
                    lines.setdefault(text, []).append(node.lineno)
    ordered = sorted(lines.items(), key=lambda item: min(item[1]))
    return [
        f"{text} (line{'s' if len(at) > 1 else ''} {', '.join(map(str, sorted(at)))})"
        for text, at in ordered
    ]


def _snapshot(repo: str, rev: str, package: str) -> tuple[Any, dict[str, ast.Module]]:
    """The import graph and each module's parsed source at ``rev``."""
    path = _package_path(repo, rev, package)
    with tempfile.TemporaryDirectory() as tmp:
        archive = _git(repo, "archive", "--format=tar", rev, path)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmp, filter="data")
        root = Path(tmp, path).parent
        # grimp locates the package through the import system, so the export
        # must lead sys.path; the caches are invalidated because the base and
        # head exports share a package name.
        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        try:
            graph = grimp.build_graph(package, cache_dir=None)
        finally:
            sys.path.remove(str(root))
        trees = {}
        for module in graph.modules:
            stem = root.joinpath(*module.split("."))
            source = stem / "__init__.py" if stem.is_dir() else stem.with_suffix(".py")
            if source.is_file():
                trees[module] = ast.parse(source.read_bytes())
    return graph, trees


def _edges(graph: Any) -> set[tuple[str, str]]:
    return {
        (module, imported)
        for module in graph.modules
        for imported in graph.find_modules_directly_imported_by(module)
    }


def _symbols(trees: dict[str, ast.Module]) -> set[str]:
    return {
        f"{m}.{name}" for m, tree in trees.items() for name in _public_symbols(tree)
    }


def _net_loc(repo: str, base: str, head: str, path: str) -> int:
    args = ("diff", "--numstat", "--no-renames", base, head, "--", path)
    numstat = _git(repo, *args).decode()
    net = 0
    for line in numstat.splitlines():
        added, deleted, name = line.split("\t")
        if name.endswith(".py") and added != "-":
            net += int(added) - int(deleted)
    return net


def measure(repo: str, package: str, base: str, head: str) -> dict[str, Any]:
    base_graph, base_trees = _snapshot(repo, base, package)
    head_graph, head_trees = _snapshot(repo, head, package)
    new_modules = sorted(head_graph.modules - base_graph.modules)
    symbols = sorted(_symbols(head_trees) - _symbols(base_trees))
    edges = sorted(_edges(head_graph) - _edges(base_graph))
    flagged = {}
    for module in new_modules:
        importers = head_graph.find_modules_that_directly_import(module)
        reasons = [f"fan-in 1 (imported only by {m})" for m in importers]
        if len(reasons) != 1 or module.rpartition(".")[0] in importers:
            reasons = []
        if module in head_trees:
            reasons += _private_reads(head_trees[module])
        if reasons:
            flagged[module] = reasons
    net = _net_loc(repo, base, head, _package_path(repo, head, package))
    return {
        "package": package,
        "base": base,
        "head": head,
        "net_loc": net,
        "new_modules": new_modules,
        "new_public_symbols": symbols,
        "new_edges": [list(edge) for edge in edges],
        "flagged_modules": flagged,
        "public_symbols_per_100_loc": 100 * len(symbols) / net if net > 0 else None,
        "edges_per_100_loc": 100 * len(edges) / net if net > 0 else None,
    }


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def render(report: dict[str, Any]) -> str:
    by_module: dict[str, list[str]] = {}
    for symbol in report["new_public_symbols"]:
        module, name = symbol.rsplit(".", 1)
        by_module.setdefault(module, []).append(name)
    symbols, edges = report["new_public_symbols"], report["new_edges"]
    lines = [
        (
            f"Surface area of {report['package']}, {report['base']}..{report['head']}"
            f" (net LOC {report['net_loc']:+d})"
        ),
        "",
        f"New modules ({len(report['new_modules'])}):",
        *(f"  {module}" for module in report["new_modules"]),
        (
            f"New public symbols ({len(symbols)},"
            f" {_rate(report['public_symbols_per_100_loc'])} per 100 net LOC):"
        ),
        *(f"  {module}: {', '.join(names)}" for module, names in by_module.items()),
        (
            f"New import edges ({len(edges)},"
            f" {_rate(report['edges_per_100_loc'])} per 100 net LOC):"
        ),
        *(f"  {importer} -> {imported}" for importer, imported in edges),
        f"Flagged new modules ({len(report['flagged_modules'])}):",
    ]
    for module, reasons in report["flagged_modules"].items():
        lines += [f"  {module}: {reason}" for reason in reasons]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="git repository to read")
    parser.add_argument("--package", required=True, help="top-level package name")
    parser.add_argument("--base", required=True, help="revision to measure from")
    parser.add_argument("--head", default="HEAD", help="revision to measure to")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)
    report = measure(args.repo, args.package, args.base, args.head)
    print(json.dumps(report, indent=2) if args.json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
