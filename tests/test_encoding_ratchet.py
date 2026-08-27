"""Every file read or write names its encoding.

Windows defaults to the ANSI codepage (cp1252 on the machine this was
written for), so a bare read_text() crashes on any non-ASCII byte -- which
is how `pixi run audit` came to be unusable there while macOS stayed green.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CALL = re.compile(r"\.(?:read_text|write_text)\(")


def sources():
    for d in ("scripts", "hooks"):
        yield from sorted((REPO / d).glob("*.py"))


def _call_args_missing_encoding(line: str) -> bool:
    """True if any read_text/write_text call on this line lacks encoding=.

    A plain [^)]* lookahead breaks on calls whose arguments contain their
    own parentheses (e.g. write_text("\n".join(x), encoding="utf-8")) --
    it stops at the first ")" and never sees the kwarg. Counting paren
    depth finds the call's real closing paren before checking.
    """
    for m in CALL.finditer(line):
        depth = 1
        i = m.end()
        while i < len(line) and depth > 0:
            if line[i] == "(":
                depth += 1
            elif line[i] == ")":
                depth -= 1
            i += 1
        if "encoding=" not in line[m.end() : i - 1]:
            return True
    return False


def test_no_bare_read_or_write_text():
    offenders = []
    for path in sources():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _call_args_missing_encoding(line):
                offenders.append(f"{path.relative_to(REPO)}:{n}")
    assert not offenders, "read_text/write_text without encoding=: " + ", ".join(
        offenders
    )
