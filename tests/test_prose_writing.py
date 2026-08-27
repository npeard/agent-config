"""Contract tests for hooks/prose-writing.py.

The hook is a JSON filter -- a payload on stdin, an optional payload on
stdout -- so it is exercised through that contract as a subprocess, like
tests/test_promotion_check.py.

TMPDIR is redirected per test because the once-per-session guard keeps a stamp
file under the temp directory. Without that, the guard's own tests would leak
into each other and, worse, into a real session's state.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "prose-writing.py"
# Derived, not hardcoded: the hook computes its master-repo path from
# expanduser("~/..."), so a literal /Users/<name> here would disagree with it
# on any other machine and every self-guard case would fail while the hook was
# behaving correctly.
PROJECTS = Path.home() / "Documents" / "Projects"
MASTER = str(PROJECTS / "claude-config")
THESIS = str(PROJECTS / "stanford-thesis")
PAPER = str(PROJECTS / "dispersion-engineering")


def run_hook(payload: dict, state: Path) -> str:
    # Created here, not left to the caller: tempfile.gettempdir() silently
    # ignores a TMPDIR that does not exist and falls back to the real system
    # temp directory, which would leak stamp files between tests and make the
    # once-per-session tests pass or fail depending on execution order.
    state.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "TMPDIR": str(state)},
    )
    return result.stdout.strip()


def fired(payload: dict, state: Path) -> bool:
    out = run_hook(payload, state)
    if not out:
        return False
    # A fired hook must emit the shape Claude Code expects, not just text.
    parsed = json.loads(out)
    assert parsed["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    context = parsed["hookSpecificOutput"]["additionalContext"]
    # Naming both skills is the point of the hook: an advisory that says
    # "consider the writing workflow" without naming what to invoke is a
    # reminder the reader cannot act on.
    assert "writing-orchestration" in context
    assert "humanizer" in context
    return True


def write(path: str, session: str = "s1") -> dict:
    return {"session_id": session, "tool_input": {"file_path": path}}


class TestFiresOnProse:
    @pytest.mark.parametrize(
        "path",
        [
            f"{THESIS}/main.tex",
            f"{THESIS}/chapters/ch3.tex",
            f"{THESIS}/appendices/a1.tex",
            f"{THESIS}/biblio.bib",
            f"{THESIS}/notes/idea.txt",
            f"{PAPER}/main.tex",
        ],
    )
    def test_fires(self, path: str, tmp_path: Path):
        assert fired(write(path), tmp_path), path

    def test_outline_fires(self, tmp_path: Path):
        """An outline is the argument, so drafting one is prose work. This is
        the borderline case the spec decided explicitly."""
        assert fired(write(f"{THESIS}/OUTLINE.md"), tmp_path)


class TestSilentOnEverythingElse:
    @pytest.mark.parametrize(
        "path",
        [
            f"{THESIS}/scripts/figure.py",
            f"{THESIS}/pyproject.toml",
            f"{THESIS}/Snakefile",
            f"{THESIS}/CLAUDE.md",
            f"{THESIS}/README.md",
            # Bookkeeping, not prose -- the other half of the OUTLINE.md
            # decision above.
            f"{THESIS}/TASKS.md",
            f"{THESIS}/build/main/main.tex",
            f"{THESIS}/docs/superpowers/specs/x.md",
            f"{THESIS}/.github/workflows/ci.md",
            f"{THESIS}/skills/some-skill/reference.md",
            f"{THESIS}/.pixi/envs/dev/share/doc/notes.txt",
            f"{PAPER}/scratch/throwaway.tex",
            # Agent configuration is Markdown but is not prose work.
            f"{THESIS}/.claude/agents/reviewer.md",
            f"{THESIS}/.claude/commands/build.md",
            # A flat skills/*.md slipped through when the pattern required
            # two levels below skills/.
            f"{THESIS}/skills/flat.md",
            f"{THESIS}/.tox/py313/notes.md",
            # Excluded on the stem, so one entry covers every prose suffix.
            # A .rst project otherwise burned its one advisory on a README.
            f"{THESIS}/README.rst",
            f"{THESIS}/CHANGELOG.rst",
            f"{THESIS}/readme.txt",
            f"{THESIS}/HISTORY.rst",
            f"{THESIS}/docs/_build/html/notes.md",
        ],
    )
    def test_silent(self, path: str, tmp_path: Path):
        assert not fired(write(path), tmp_path), path

    def test_silent_under_the_system_temp_directory(self, tmp_path: Path):
        """This harness sends throwaway files to a scratchpad under the temp
        directory, and prose written there is by definition disposable.

        The path has to live under the temp directory *the hook sees*, which
        run_hook redirects to `state` -- comparing against the real system
        temp dir here would test nothing.
        """
        assert not fired(write(f"{tmp_path}/notes.md"), tmp_path)

    def test_a_real_prose_suffix_that_is_not_excluded_still_fires(self, tmp_path: Path):
        """Guards the stem generalization against over-matching."""
        assert fired(write(f"{THESIS}/chapters/introduction.rst"), tmp_path)


class TestMasterRepoSelfGuard:
    """Writing a skill in claude-config is config work, not prose work, and
    promotion-check.py already speaks there. Two advisories on one write is
    how a hook teaches people to ignore hooks."""

    @pytest.mark.parametrize(
        "path",
        [
            f"{MASTER}/skills/humanizer/patterns.md",
            f"{MASTER}/README.md",
            # normpath must collapse the traversal before the prefix test,
            # which is the bug class fixed in 237c1d7.
            f"{MASTER}/skills/../README.md",
            f"{MASTER}//README.md",
        ],
    )
    def test_silent_inside_master(self, path: str, tmp_path: Path):
        assert not fired(write(path), tmp_path), path

    def test_sibling_with_shared_prefix_still_fires(self, tmp_path: Path):
        """`claude-config-other` is not inside `claude-config`; a plain
        startswith without the separator would swallow it."""
        assert fired(write(f"{MASTER}-other/main.tex"), tmp_path)


@pytest.fixture
def prose_project(tmp_path: Path) -> Path:
    """A git-rooted project with a chapter subdirectory.

    Built here rather than pointed at ~/Documents/Projects/stanford-thesis,
    because "same project" means "same git root": against a real repo the
    grouping tests below pass on this machine and fail on one where that
    checkout does not exist, which is the fresh-machine install the README
    documents. The state directory is a sibling, not a child, so the stamp
    files cannot be mistaken for project content.
    """
    root = tmp_path / "thesis"
    (root / "chapters").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


class TestOncePerSession:
    """A thesis session writes main.tex dozens of times, and an advisory
    re-injected on every write costs the same context as the useful first one
    while buying less each time."""

    def test_second_write_in_the_same_session_is_silent(
        self, prose_project: Path, tmp_path: Path
    ):
        state = tmp_path / "state"
        assert fired(write(f"{prose_project}/main.tex"), state)
        assert not fired(write(f"{prose_project}/main.tex"), state)

    def test_a_second_file_in_the_same_project_is_also_silent(
        self, prose_project: Path, tmp_path: Path
    ):
        """Both files share a git root, so they are one project even though
        they are in different directories."""
        state = tmp_path / "state"
        assert fired(write(f"{prose_project}/main.tex"), state)
        assert not fired(write(f"{prose_project}/chapters/ch3.tex"), state)

    def test_a_different_project_still_fires(self, prose_project: Path, tmp_path: Path):
        state = tmp_path / "state"
        other = tmp_path / "paper"
        (other / ".git").mkdir(parents=True)
        assert fired(write(f"{prose_project}/main.tex"), state)
        assert fired(write(f"{other}/main.tex"), state)

    def test_without_a_git_root_the_directory_is_the_project(self, tmp_path: Path):
        """Pinning the documented fallback rather than leaving it to chance.

        Loose prose outside a repo is grouped per directory, so a sibling
        subdirectory is a separate project and fires again. That is noisier
        than the git-rooted case, and it is the honest consequence of having
        no better boundary to key on.
        """
        state = tmp_path / "state"
        loose = tmp_path / "loose"
        (loose / "sub").mkdir(parents=True)
        assert fired(write(f"{loose}/a.tex"), state)
        assert not fired(write(f"{loose}/b.tex"), state)
        assert fired(write(f"{loose}/sub/c.tex"), state)

    def test_a_new_session_fires_again(self, prose_project: Path, tmp_path: Path):
        state = tmp_path / "state"
        assert fired(write(f"{prose_project}/main.tex", session="s1"), state)
        assert fired(write(f"{prose_project}/main.tex", session="s2"), state)

    def test_no_session_id_fires_every_time(self, tmp_path: Path):
        """Fail open: the advisory is cheap and a missed one is the worse
        outcome, so an unkeyable payload is not silently suppressed."""
        payload = {"tool_input": {"file_path": f"{THESIS}/main.tex"}}
        assert fired(payload, tmp_path)
        assert fired(payload, tmp_path)


class TestPayloadHandling:
    def test_missing_file_path_is_silent(self, tmp_path: Path):
        assert not fired({"tool_input": {}}, tmp_path)

    def test_empty_payload_is_silent(self, tmp_path: Path):
        assert not fired({}, tmp_path)

    @pytest.mark.parametrize("value", [None, "a string", 42, []])
    def test_non_dict_tool_input_declines_rather_than_raising(
        self, value: object, tmp_path: Path
    ):
        """`.get("tool_input", {}).get(...)` raised on a null tool_input,
        contradicting this hook's stated promise to decline quietly."""
        assert not fired({"session_id": "s", "tool_input": value}, tmp_path)

    @pytest.mark.parametrize("body", ["null", "[]", '"a string"', "42"])
    def test_non_object_payload_declines_rather_than_raising(
        self, body: str, tmp_path: Path
    ):
        """json.load only raises for *malformed* JSON, so a valid non-object
        body decodes fine and then has no .get. Sent as raw text rather than
        through write() because the point is the shape of the whole payload.
        """
        state = tmp_path / "state"
        state.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=body,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "TMPDIR": str(state)},
        )
        assert result.returncode == 0, result.stderr
        assert not result.stdout.strip()

    @pytest.mark.parametrize("value", [12345, ["a"], {"a": 1}, True])
    def test_non_string_file_path_declines_rather_than_raising(
        self, value: object, tmp_path: Path
    ):
        """A non-string path reached os.path.normpath and raised TypeError
        there, which a truthiness check cannot prevent."""
        assert not fired(
            {"session_id": "s", "tool_input": {"file_path": value}}, tmp_path
        )

    def test_malformed_stdin_does_not_traceback(self, tmp_path: Path):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            # check=False on purpose: a non-zero exit is the failure this test
            # exists to catch, so it must be asserted, not raised.
            check=False,
            env={**os.environ, "TMPDIR": str(tmp_path)},
        )
        assert result.returncode == 0
        assert not result.stdout.strip()


class TestPathCasePreservation:
    """`project_root` walks the filesystem looking for `.git`, so it must be
    given the real-case path. Everything else here lowercases before matching.

    Asserted against the function rather than through the subprocess contract
    because macOS is case-insensitive: a behavioural test passes here whether
    or not the bug is present, and would only fail on the Linux and Windows
    platforms pixi.toml declares. That is exactly the shape of bug worth
    pinning where it can actually be seen.
    """

    def hook_module(self):
        # The filename has a hyphen, so it is not importable by name.
        spec = importlib.util.spec_from_file_location("prose_writing", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_resolve_keeps_case_and_canonical_drops_it(self, tmp_path: Path):
        hook = self.hook_module()
        target = str(tmp_path / "Thesis" / "Main.tex")
        assert "Thesis" in hook.resolve(target)
        assert "thesis" in hook.canonical(target)

    def test_project_root_finds_a_mixed_case_git_root(self, tmp_path: Path):
        hook = self.hook_module()
        root = tmp_path / "Thesis"
        (root / "chapters").mkdir(parents=True)
        (root / ".git").mkdir()
        found = hook.project_root(hook.resolve(str(root / "chapters" / "ch3.tex")))
        assert found == hook.resolve(str(root)), (
            "the git walk missed a mixed-case root, so every chapter would "
            "count as its own project and the advisory would re-fire"
        )


class TestRegistration:
    """That a marker exists at all is already asserted repo-wide by
    test_register_hooks.py. What only this file can check is that the marker
    and the payload name the *same* event: registered on one event while
    emitting the other, the hook is wired to a trigger whose output shape it
    does not match, and both tests pass in isolation."""

    def test_the_marker_event_matches_the_emitted_event(self, tmp_path: Path):
        head = HOOK.read_text().splitlines()[:10]
        markers = [line for line in head if "claude-hook:" in line]
        assert len(markers) == 1, markers
        declared = markers[0].split("claude-hook:")[1].split()[0]

        out = run_hook(write(f"{tmp_path}/main.tex"), tmp_path / "state")
        emitted = json.loads(out)["hookSpecificOutput"]["hookEventName"]
        assert declared == emitted, f"registered as {declared}, emits {emitted}"

    def test_the_matcher_covers_the_tools_that_write_files(self):
        """Bash included, because a session told to edit with sed or a heredoc
        routes none of its writes through Write or Edit, and a hook that only
        matches those is dead there. One marker with an alternation rather
        than two markers: register_hooks.apply finds an existing entry by
        filename alone, so two markers for one file under one event fight over
        a single entry and `--check` never comes back clean."""
        import register_hooks

        matchers = [
            m for name, _, m in register_hooks.declared_hooks() if name == HOOK.name
        ]
        assert len(matchers) == 1, matchers
        assert set(matchers[0].split("|")) == {"Write", "Edit", "Bash"}


def bash(command: str, cwd: str = THESIS, session: str = "s1") -> dict:
    return {
        "session_id": session,
        "tool_input": {"command": command},
        "cwd": cwd,
    }


class TestBashWrites:
    """A hook matching only Write|Edit never fires in a session told to edit
    with sed and heredocs, which is most of them. The advisory is worth most
    before the draft exists, so this stays PreToolUse for Bash too."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cat > {THESIS}/ch3.tex <<EOF\nbody\nEOF",
            f"sed -i '' 's/a/b/' {THESIS}/main.tex",
            f"echo x >> {THESIS}/biblio.bib",
            f"tee {PAPER}/main.tex < draft",
            f"cp draft.tex {THESIS}/ch1.tex",
        ],
    )
    def test_a_write_shaped_command_fires(self, command: str, tmp_path: Path):
        assert fired(bash(command), tmp_path), command

    def test_a_relative_path_resolves_against_the_payload_cwd(self, tmp_path: Path):
        assert fired(bash("echo x > ch4.tex", cwd=THESIS), tmp_path)

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -rn TODO {THESIS}/main.tex",
            f"cat {THESIS}/main.tex",
            f"wc -w {THESIS}/*.tex",
            f"grep TODO {THESIS}/main.tex > /dev/null",
            f"echo x > {THESIS}/README.md",
            f"echo x > {MASTER}/notes.md",
            f"echo x > {THESIS}/src/main.py",
            "pixi run format",
        ],
    )
    def test_a_read_only_or_uninteresting_command_is_silent(
        self, command: str, tmp_path: Path
    ):
        assert not fired(bash(command), tmp_path), command

    def test_an_unparsable_command_is_silent(self, tmp_path: Path):
        assert not fired(bash(f"echo 'oops > {THESIS}/x.tex"), tmp_path)

    def test_no_part_of_the_command_reaches_the_output(self, tmp_path: Path):
        """The Write branch names the file it was handed, which the session
        itself authored. A path this parser lifts out of a shell command is a
        different thing: it can be any string, spaces and newlines included,
        so naming it would put text the session did not author into context.
        """
        marker = "ZZUNIQUEZZ"
        out = run_hook(bash(f"echo x > {THESIS}/{marker}/ch9.tex"), tmp_path)
        assert out
        assert marker not in out
        assert THESIS not in out

    def test_the_advisory_is_still_once_per_session_per_project(self, tmp_path: Path):
        """A Write and a Bash write in one project are one project, so the
        second must be silent whichever tool got there first."""
        assert fired(write(f"{THESIS}/main.tex"), tmp_path)
        assert not fired(bash(f"echo x >> {THESIS}/ch2.tex"), tmp_path)
