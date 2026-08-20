"""Contract tests for hooks/promotion-check.py.

The hook is a pure JSON filter -- a payload on stdin, an optional payload on
stdout -- so it is exercised through that contract as a subprocess. No git or
filesystem state is involved, and the tests stay valid however the internals
are refactored.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "promotion-check.py"
# Derived, not hardcoded: the hook computes its master-repo path from
# expanduser("~/..."), so a literal /Users/<name> here would disagree with it
# on any other machine -- including the "Install (new machine)" path the
# README documents -- and every self-guard case would fail while the hook was
# behaving correctly.
PROJECTS = Path.home() / "Documents" / "Projects"
MASTER = str(PROJECTS / "claude-config")
OTHER = str(PROJECTS / "other-project")


def run_hook(payload: dict) -> str:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def fired(payload: dict) -> bool:
    out = run_hook(payload)
    if not out:
        return False
    # A fired hook must emit the shape Claude Code expects, not just text.
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert parsed["hookSpecificOutput"]["additionalContext"]
    return True


def write(path: str) -> dict:
    return {"tool_input": {"file_path": path}}


class TestMatchesRealFilenames:
    """The patterns are lowercase but os.path.normcase only lowercases on
    Windows, so on macOS and Linux the hook silently never fired for the
    real, capitalised filenames it exists to catch."""

    @pytest.mark.parametrize(
        "path",
        [
            f"{OTHER}/CLAUDE.md",
            f"{OTHER}/claude.md",
            f"{OTHER}/nested/dir/CLAUDE.md",
            f"{OTHER}/skills/my-skill/SKILL.md",
            f"{OTHER}/skills/my-skill/skill.md",
            f"{OTHER}/memory/some-fact.md",
            f"{OTHER}/.claude/memory/some-fact.md",
        ],
    )
    def test_fires(self, path: str):
        assert fired(write(path)), path


class TestIgnoresEverythingElse:
    @pytest.mark.parametrize(
        "path",
        [
            f"{OTHER}/src/main.py",
            f"{OTHER}/README.md",
            f"{OTHER}/docs/design.md",
            f"{OTHER}/skills/my-skill/reference.md",
        ],
    )
    def test_silent(self, path: str):
        assert not fired(write(path)), path


class TestMasterRepoSelfGuard:
    """Editing the master repo is the promotion, so nagging there is noise."""

    @pytest.mark.parametrize(
        "path",
        [
            f"{MASTER}/CLAUDE.md",
            f"{MASTER}/skills/quantikz/SKILL.md",
            # normpath must collapse the traversal before the prefix test,
            # which is the bug class fixed in 237c1d7.
            f"{MASTER}/skills/../CLAUDE.md",
            f"{MASTER}//CLAUDE.md",
            f"{MASTER}/./CLAUDE.md",
        ],
    )
    def test_silent_inside_master(self, path: str):
        assert not fired(write(path)), path

    def test_sibling_with_shared_prefix_still_fires(self):
        """`claude-config-other` is not inside `claude-config`; a plain
        startswith without the separator would swallow it."""
        assert fired(write(f"{MASTER}-other/CLAUDE.md"))


class TestPayloadHandling:
    def test_missing_file_path_is_silent(self):
        assert not fired({"tool_input": {}})

    def test_empty_payload_is_silent(self):
        assert not fired({})

    def test_falls_back_to_tool_response_filepath(self):
        assert fired({"tool_response": {"filePath": f"{OTHER}/CLAUDE.md"}})

    def test_tool_input_wins_over_tool_response(self):
        assert not fired(
            {
                "tool_input": {"file_path": f"{OTHER}/src/main.py"},
                "tool_response": {"filePath": f"{OTHER}/CLAUDE.md"},
            }
        )


class TestInstalledSymlinkPaths:
    """install.sh symlinks ~/.claude/CLAUDE.md and ~/.claude/skills/<name>
    into the master repo, so editing the config through its installed path
    must still be recognised as editing the master repo."""

    def test_silent_through_the_installed_claude_md_symlink(self):
        installed = Path.home() / ".claude" / "CLAUDE.md"
        if not installed.is_symlink():
            pytest.skip("config not installed on this machine")
        if not str(Path(os.path.realpath(installed))).startswith(MASTER):
            pytest.skip("installed config does not point at this checkout")
        assert not fired(write(str(installed)))

    def test_still_fires_for_a_symlink_outside_the_master_repo(self, tmp_path: Path):
        target = tmp_path / "CLAUDE.md"
        target.write_text("x")
        link = tmp_path / "linked-CLAUDE.md"
        link.symlink_to(target)
        assert fired(write(str(link)))
