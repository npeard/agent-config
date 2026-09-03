"""Every file read or write names its encoding.

Windows defaults to the ANSI codepage (cp1252 on the machine this was
written for), so a bare read_text() crashes on any non-ASCII byte -- which
is how `pixi run audit` came to be unusable there while macOS stayed green.
The same default applies to the builtin open() in text mode, where the
failure is quieter: a mis-decoded marker line simply compares unequal, so
audit-owed.py re-appended the same obligation on every commit instead of
raising.

Checked against the parse tree rather than line by line. "open" is an
ordinary English word and these modules are mostly prose, so a textual
scan flagged docstrings, and a ratchet that cries wolf gets deleted rather
than obeyed. The tree also distinguishes the builtin open() from os.open()
-- which takes flags and no encoding at all -- for free, and sees a call
whose arguments run over several lines.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def sources():
    # install.py is the repo's most destructive file and reads the stub it
    # compares against, so it is scanned despite living at the root. tests/
    # stays out: a fixture may deliberately write undecodable bytes.
    yield REPO / "install.py"
    for d in ("scripts", "hooks"):
        yield from sorted((REPO / d).glob("*.py"))


def _mode_of(call: ast.Call) -> str:
    """The literal mode string this open() call passes, positional or kwarg."""
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
        return str(call.args[1].value)
    return ""


def _is_binary(call: ast.Call) -> bool:
    # Binary mode forbids encoding=, so demanding it there would be wrong.
    return "b" in _mode_of(call).replace("+", "")


def offenders_in(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            if _is_binary(node):
                continue
        elif isinstance(func, ast.Attribute) and func.attr in {
            "read_text",
            "write_text",
        }:
            pass
        else:
            continue
        if not any(kw.arg == "encoding" for kw in node.keywords):
            lines.append(node.lineno)
    return sorted(lines)


def test_no_bare_read_write_text_or_open():
    offenders = []
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.relative_to(REPO)}:{n}" for n in offenders_in(tree)]
    assert not offenders, "text I/O without encoding=: " + ", ".join(offenders)


FLAGGED = [
    "with open(marker) as fh:\n    pass\n",
    "open(p, 'r')\n",
    "x = p.read_text()\n",
    "p.write_text(s)\n",
    'open(\n    path,\n    "w",\n)\n',
]

ALLOWED = [
    'with open(m, encoding="utf-8") as fh:\n    pass\n',
    'open(p, "rb")\n',
    'open(p, mode="rb")\n',
    'open("a", "r+b")\n',
    "fd = os.open(mk, os.O_WRONLY | os.O_CREAT, 0o644)\n",
    'p.write_text(sep.join(x), encoding="utf-8")\n',
    "# a bare open( in a comment\nx = 1\n",
    'doc = "you can open(x) safely"\n',
    'def f():\n    """A hook may open( a file."""\n',
    'subprocess.Popen(["x"])\n',
    'gzip.open(p, "rt")\n',
]


@pytest.mark.parametrize("src", FLAGGED)
def test_the_ratchet_catches_what_it_claims_to(src):
    assert offenders_in(ast.parse(src))


@pytest.mark.parametrize("src", ALLOWED)
def test_the_ratchet_does_not_cry_wolf(src):
    """A ratchet with false positives gets deleted rather than obeyed, so the
    exemptions -- binary mode, os.open, and the word appearing in prose --
    are pinned here rather than rediscovered by whoever it next fails on."""
    assert not offenders_in(ast.parse(src))
