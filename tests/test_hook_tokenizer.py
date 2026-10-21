"""The shell tokenizer the hooks share, and audit-owed.py's retry around it.

hooks/hook_lib.py's tokenize(line) is what promotion-check.py,
prose-writing.py and poll-guard.py call; audit-owed.py wraps it with one
quote-stripped retry. Both are exercised here, against the contract rather
than the implementation.

shlex(posix=True) always treats "\\" as an escape character, which ate the
separators out of a native Windows path like "C:\\Users\\...\\AGENTS.md" and
made it fail to match the directory it lives in. Doubling the backslashes
inside text shaped like a native Windows path is the fix under test, and the
*shape* is the key, not the platform: the Bash tool on Windows runs Git Bash,
so a POSIX escape in a command there is genuine and must survive untouched.
Every case below therefore runs on every platform. audit-owed.py's retry has
no input left that returns None -- stripping every quote character forecloses
the only thing shlex raises on here -- so its None contract is not asserted;
the retry is pinned directly instead.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"


def load(name: str):
    # The filenames have hyphens, so none is importable by name.
    path = HOOKS_DIR / name
    module_name = name.replace("-", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK_LIB = load("hook_lib.py")
AUDIT_OWED = load("audit-owed.py")
TOKENIZERS = {"hook_lib": HOOK_LIB.tokenize, "audit-owed": AUDIT_OWED.tokenize}


@pytest.fixture(params=sorted(TOKENIZERS))
def tokenize(request):
    return TOKENIZERS[request.param]


WINDOWS_PATH = r"C:\Users\me\Documents\Projects\agent-config\AGENTS.md"
POSIX_PATH = "/home/me/Documents/Projects/agent-config/AGENTS.md"


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


def test_unparsable_input_declines_by_returning_none_not_a_list():
    """None on an unbalanced quote, never an empty list or a partial one: an
    unbalanced quote is the only input shlex(posix=True) raises on here, and a
    caller that lifts paths must not guess at one.
    """
    assert HOOK_LIB.tokenize("echo 'unterminated") is None


def test_audit_owed_retry_recovers_the_mandated_commit_form_not_none():
    """audit-owed.py's tokenize has no input that returns None: its retry
    strips every quote character, and an unbalanced quote -- the only thing
    that raises here -- cannot survive having all quote characters removed.
    That retry exists specifically to recover
    `git commit -m "$(cat <<'EOF' ... EOF)"`, so pin the recovery itself
    rather than asserting a None case this hook cannot produce.
    """
    tokens = AUDIT_OWED.tokenize("git commit -m \"$(cat <<'EOF'")
    assert tokens[:3] == ["git", "commit", "-m"]


def test_windows_path_survives_even_with_balanced_quotes(tokenize):
    """A quoted Windows path -- the shape a session actually writes -- must
    also keep its separators, not just a bare one."""
    tokens = tokenize(f'cat "{WINDOWS_PATH}"')
    assert tokens == ["cat", WINDOWS_PATH]


def test_a_quoted_windows_path_containing_a_space_stays_one_token(tokenize):
    """The doubling is applied to runs that stop at whitespace, so a quoted
    path with a space in it is two runs. The quotes must still rejoin them."""
    spaced = r"C:\Users\me\My Documents\CLAUDE.md"
    assert tokenize(f'cat "{spaced}"') == ["cat", spaced]


class TestPosixEscapesSurvive:
    """A POSIX command must parse identically on every platform.

    The Bash tool on Windows runs Git Bash, so backslashes in a command there
    are genuine POSIX escapes. Doubling every backslash would corrupt these
    two shapes, and the hooks that extract paths would invent a destination
    that was never written -- the error hook_lib.tokenize declines to risk.
    """

    def test_an_escaped_space_keeps_one_path_in_one_token(self, tokenize):
        assert tokenize(r"cp /c/Users/me/a\ b.md /c/dest/") == [
            "cp",
            "/c/Users/me/a b.md",
            "/c/dest/",
        ]

    def test_an_escaped_semicolon_does_not_become_a_stray_backslash(self, tokenize):
        assert tokenize(r'find . -name "*.tmp" -exec rm {} \;') == [
            "find",
            ".",
            "-name",
            "*.tmp",
            "-exec",
            "rm",
            "{}",
            ";",
        ]
