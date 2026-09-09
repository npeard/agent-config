"""Contract tests for hooks/promotion-check.py.

The hook is a pure JSON filter -- a payload on stdin, an optional payload on
stdout -- so it is exercised through that contract as a subprocess. No git or
filesystem state is involved, and the tests stay valid however the internals
are refactored.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import platform_paths_helper as pp
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


def run_hook(payload: dict, home: Path | None = None) -> str:
    env = None
    if home is not None:
        # The hook derives MASTER_REPO from expanduser("~/..."), so pointing
        # both names at a scratch home lets a test build the whole scenario
        # instead of testing whatever this machine happens to have installed.
        env = os.environ | {"HOME": str(home), "USERPROFILE": str(home)}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def fired(payload: dict, home: Path | None = None) -> bool:
    out = run_hook(payload, home)
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
            f"{OTHER}/AGENTS.md",
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
            f"{MASTER}/AGENTS.md",
            f"{MASTER}/skills/quantikz/SKILL.md",
            # normpath must collapse the traversal before the prefix test,
            # which is the bug class fixed in 237c1d7.
            f"{MASTER}/skills/../AGENTS.md",
            f"{MASTER}//AGENTS.md",
            f"{MASTER}/./AGENTS.md",
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
    """The installer links ~/.claude/skills/<name> into the master repo, so
    editing the config through its installed path must still be recognised as
    editing the master repo."""

    def test_silent_through_a_link_into_the_master_repo(self, tmp_path: Path):
        """Constructed in a scratch home rather than read off the real one.
        Keying on whether this machine happens to have the config installed
        meant the assertion skipped on every CI runner, so the case the
        hook's realpath exists for went unexercised exactly where nobody
        would notice. link_dir is the installer's own primitive -- a junction
        on Windows, a symlink elsewhere -- and needs elevation on neither.
        """
        master = tmp_path / "Documents" / "Projects" / "claude-config"
        (master / "skills" / "quantikz").mkdir(parents=True)
        (master / "skills" / "quantikz" / "SKILL.md").write_text("x", encoding="utf-8")
        installed = tmp_path / ".claude" / "skills"
        installed.mkdir(parents=True)
        pp.link_dir(master / "skills" / "quantikz", installed / "quantikz")
        assert not fired(write(str(installed / "quantikz" / "SKILL.md")), home=tmp_path)

    def test_still_fires_for_a_link_outside_the_master_repo(self, tmp_path: Path):
        """The other half of the same contract: resolving links must not turn
        into resolving them away, or the hook goes silent for everything."""
        master = tmp_path / "Documents" / "Projects" / "claude-config"
        master.mkdir(parents=True)
        elsewhere = tmp_path / "other-project" / "skills" / "quantikz"
        elsewhere.mkdir(parents=True)
        (elsewhere / "SKILL.md").write_text("x", encoding="utf-8")
        link = tmp_path / "linked-skill"
        pp.link_dir(elsewhere, link)
        assert fired(write(str(link / "SKILL.md")), home=tmp_path)

    @pytest.mark.skipif(
        os.name == "nt",
        reason=(
            "creating a file symlink on Windows needs elevation or Developer "
            "Mode; junctions are directory-only so they cannot substitute. "
            "The hook's path-canonicalisation is still covered by the other "
            "tests in this file."
        ),
    )
    def test_still_fires_for_a_symlink_outside_the_master_repo(self, tmp_path: Path):
        target = tmp_path / "CLAUDE.md"
        target.write_text("x")
        link = tmp_path / "linked-CLAUDE.md"
        link.symlink_to(target)
        assert fired(write(str(link)))


def bash(command: str, cwd: str = OTHER) -> dict:
    return {"tool_input": {"command": command}, "cwd": cwd}


class TestBashWrites:
    """Sessions are routinely told to edit files with `sed`, a heredoc or a
    short script rather than the Write and Edit tools, and in such a session a
    hook registered only for Write|Edit never fires at all. Verified on this
    repo's own history: 22 commits of exactly the work this hook exists to
    catch, zero firings. audit-owed.py already reads `tool_input.command` for
    the same reason.
    """

    @pytest.mark.parametrize(
        "command",
        [
            f"sed -i '' 's/a/b/' {OTHER}/CLAUDE.md",
            f"sed -i.bak 's/a/b/' {OTHER}/skills/s/SKILL.md",
            f"echo hi >> {OTHER}/CLAUDE.md",
            f"echo hi > {OTHER}/memory/fact.md",
            f"cat > {OTHER}/CLAUDE.md <<EOF\nbody\nEOF",
            f"tee -a {OTHER}/CLAUDE.md < /dev/null",
            f"cp draft.md {OTHER}/CLAUDE.md",
            f"mv draft.md {OTHER}/skills/s/SKILL.md",
            f"printf x > {OTHER}/CLAUDE.md 2>/dev/null",
            f"true; echo hi > {OTHER}/CLAUDE.md",
        ],
    )
    def test_a_write_shaped_command_fires(self, command: str):
        assert fired(bash(command)), command

    def test_a_relative_path_resolves_against_the_payload_cwd(self):
        """Resolving against the hook process's own cwd instead would land in
        whatever directory Claude Code happened to start the hook in."""
        assert fired(bash("echo hi > CLAUDE.md", cwd=OTHER))

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -rn TODO {OTHER}/CLAUDE.md",
            f"cat {OTHER}/CLAUDE.md",
            f"ls {OTHER}/skills",
            f"wc -l {OTHER}/CLAUDE.md {OTHER}/skills/s/SKILL.md",
            "grep CLAUDE.md -r .",
        ],
    )
    def test_a_read_only_command_is_silent(self, command: str):
        assert not fired(bash(command)), command

    def test_a_read_redirected_elsewhere_does_not_flag_the_file_read(self):
        """`> out.txt` makes the command write-shaped, but CLAUDE.md is still
        only being read. Flagging every path in any write-shaped command would
        make the advisory fire on searches."""
        assert not fired(bash(f"grep TODO {OTHER}/CLAUDE.md > out.txt"))

    @pytest.mark.parametrize(
        "command",
        [
            f"echo hi > {OTHER}/notes.md",
            f"sed -i '' 's/a/b/' {OTHER}/src/main.py",
            f"echo hi > {MASTER}/AGENTS.md",
            f"sed -i '' 's/a/b/' {MASTER}/skills/quantikz/SKILL.md",
        ],
    )
    def test_uninteresting_or_master_repo_targets_are_silent(self, command: str):
        assert not fired(bash(command)), command

    def test_an_unparsable_command_is_silent(self):
        assert not fired(bash("echo 'oops > x/CLAUDE.md"))

    def test_no_part_of_the_command_reaches_the_output(self):
        """The command is the one field here that can carry text the session
        did not author -- a filename pasted from another tool's output, say --
        so quoting any of it back would be the untrusted-content-into-context
        path principle 5 exists to forbid. The message is fixed prose.
        """
        marker = "ZZUNIQUEZZ"
        out = run_hook(bash(f"echo hi > {OTHER}/{marker}/CLAUDE.md"))
        assert out
        assert marker not in out
        assert OTHER not in out


class TestRegistration:
    """A Bash branch that nothing routes Bash events to is dead code.

    Asserted through register_hooks' own parser rather than by matching the
    marker text, so this checks the registration the harness would receive.
    One marker with an alternation rather than two markers: apply() finds an
    existing entry by filename alone, so two markers for one file under one
    event fight over a single entry and `--check` never comes back clean.
    """

    def test_the_hook_is_registered_for_bash_as_well_as_write_and_edit(self):
        import register_hooks

        declared = register_hooks.declared_hooks()
        matchers = [m for name, event, m in declared if name == HOOK.name]
        assert len(matchers) == 1, matchers
        assert set(matchers[0].split("|")) == {"Write", "Edit", "Bash"}

    def test_registration_is_idempotent(self):
        import register_hooks

        settings: dict = {}
        register_hooks.apply(settings, register_hooks.declared_hooks())
        assert register_hooks.apply(settings, register_hooks.declared_hooks()) == []


class TestSharedShellParser:
    """The command parser is duplicated in hooks/prose-writing.py.

    A hook is invoked by absolute path under whatever interpreter
    ~/.claude/settings.json names, so it may depend on nothing but the standard
    library, and a shared module under hooks/ is not available either:
    register_hooks registers every hooks/*.py and a test fails on any file
    there without an event marker. So the copies are deliberate, and this
    pins them to the same behaviour rather than to the same text -- a drift
    that changes nothing observable is not worth a failing test.
    """

    def module(self, name: str):
        # The filenames have hyphens, so neither is importable by name.
        path = HOOK.parent / name
        spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.mark.parametrize(
        "command",
        [
            "echo x > a/CLAUDE.md",
            "echo x >> a/b.tex",
            "cat > a/b.tex <<EOF\nbody > decoy.tex\nEOF",
            "sed -i '' 's/a/b/' a/b.tex",
            "sed 's/a/b/' a/b.tex",
            "tee a.md b.md < in",
            "cp a b/c",
            "mv a b",
            "grep TODO a.tex > out",
            "grep TODO a.tex",
            "echo 'unbalanced > a.tex",
            "true; echo x > a.tex && echo y > b.tex",
            "printf x > a.tex 2>/dev/null",
        ],
    )
    def test_both_hooks_extract_the_same_written_paths(self, command: str):
        here = self.module("promotion-check.py")
        there = self.module("prose-writing.py")
        assert here.written_paths(command, "/w") == there.written_paths(command, "/w")
