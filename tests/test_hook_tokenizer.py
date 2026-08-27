"""tokenize() agreement across the three hooks that copy it.

hooks/promotion-check.py, hooks/prose-writing.py and hooks/audit-owed.py each
define their own module-level tokenize(line) -- deliberately duplicated,
since a hook runs standalone under whatever interpreter
~/.claude/settings.json names, stdlib-only and with no sys.path manipulation,
so a shared module under hooks/ is not available to import from. This file is
the coupling that keeps the three copies honest: it does not care how any of
them is implemented, only that they agree on the contract.

shlex(posix=True) always treats "\\" as an escape character, which ate the
separators out of a native Windows path like "C:\\Users\\...\\CLAUDE.md" and
made it fail to match the directory it lives in -- the promotion-check
self-guard's concrete symptom. Backslash-doubling on os.name == "nt" is the
fix under test; audit-owed.py's tokenize additionally retries once with quote
characters stripped (the `git commit -m "$(cat <<'EOF' ... EOF)"` recovery),
which must survive alongside it. That retry also means audit-owed.py's
tokenize has no input left that returns None -- stripping every quote
character forecloses the only thing shlex raises on here -- so its None
contract is not asserted below; only promotion-check.py's and
prose-writing.py's are, and audit-owed's retry is pinned directly instead.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
HOOK_NAMES = ["promotion-check.py", "prose-writing.py", "audit-owed.py"]


def load(name: str):
    # The filenames have hyphens, so none is importable by name.
    path = HOOKS_DIR / name
    module_name = name.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULES = {name: load(name) for name in HOOK_NAMES}


@pytest.fixture(params=HOOK_NAMES)
def tokenize(request):
    return MODULES[request.param].tokenize


WINDOWS_PATH = r"C:\Users\npeard\Documents\Projects\claude-config\CLAUDE.md"
POSIX_PATH = "/home/npeard/Documents/Projects/claude-config/CLAUDE.md"


@pytest.mark.skipif(
    os.name != "nt",
    reason="tokenize() doubles backslashes only on Windows, because a backslash "
    "in a POSIX shell command is a genuine escape and doubling it there would "
    "corrupt the command. A macOS session never receives a native Windows path, "
    "so there is nothing to preserve.",
)
def test_native_windows_path_survives_as_one_token(tokenize):
    """The regression this hook set exists to catch: a bare backslash-laden
    Windows path must come back as a single token with its separators intact,
    not eaten as shlex escape characters."""
    tokens = tokenize(f"cat {WINDOWS_PATH}")
    assert tokens == ["cat", WINDOWS_PATH]


def test_posix_path_is_unchanged(tokenize):
    """macOS/Linux behaviour must not change: a POSIX path has no backslashes
    to double, so doubling must be a no-op for it regardless of platform."""
    tokens = tokenize(f"cat {POSIX_PATH}")
    assert tokens == ["cat", POSIX_PATH]


def test_double_quoting_still_groups_a_word_with_spaces(tokenize):
    tokens = tokenize('echo "hello world" foo')
    assert tokens == ["echo", "hello world", "foo"]


def test_single_quoting_still_groups_a_word_with_spaces(tokenize):
    tokens = tokenize("echo 'hello world' foo")
    assert tokens == ["echo", "hello world", "foo"]


@pytest.mark.parametrize("name", ["promotion-check.py", "prose-writing.py"])
def test_unparsable_input_declines_by_returning_none_not_a_list(name):
    """The real contract for the two hooks with no retry: None on an
    unbalanced quote, never an empty list or a partial one -- an unbalanced
    quote is the only input shlex(posix=True) raises on here, and neither
    hook recovers from it.
    """
    result = MODULES[name].tokenize("echo 'unterminated")
    assert result is None, f"{name} returned {result!r}, expected None"


def test_audit_owed_retry_recovers_the_mandated_commit_form_not_none():
    """audit-owed.py's tokenize has no input that returns None: its retry
    strips every quote character, and an unbalanced quote -- the only thing
    that raises here -- cannot survive having all quote characters removed.
    That retry exists specifically to recover
    `git commit -m "$(cat <<'EOF' ... EOF)"`, so pin the recovery itself
    rather than asserting a None case this hook cannot produce.
    """
    tokens = MODULES["audit-owed.py"].tokenize("git commit -m \"$(cat <<'EOF'")
    assert tokens[:3] == ["git", "commit", "-m"]


@pytest.mark.skipif(
    os.name != "nt",
    reason="tokenize() doubles backslashes only on Windows, because a backslash "
    "in a POSIX shell command is a genuine escape and doubling it there would "
    "corrupt the command. A macOS session never receives a native Windows path, "
    "so there is nothing to preserve.",
)
def test_windows_path_survives_even_with_balanced_quotes(tokenize):
    """A quoted Windows path -- the shape a session actually writes -- must
    also keep its separators, not just a bare one."""
    tokens = tokenize(f'cat "{WINDOWS_PATH}"')
    assert tokens == ["cat", WINDOWS_PATH]
