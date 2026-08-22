"""Contract tests for hooks/audit-owed.py.

Exercised as a subprocess through its real contract -- a payload on stdin, an
optional payload on stdout -- like the other hook tests here.

Unlike promotion-check.py this hook reads git state and writes a marker file, so
the tests give it a temporary tree. It resolves its root per call in
master_repo(), and run_hook drives it through CLAUDE_CONFIG_REPO; one test
deliberately unsets that to exercise the expanduser default, so the documented
install path cannot rot.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import run_git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "audit-owed.py"
MARKER = ".audit-owed"


@pytest.fixture
def fake_master(tmp_path: Path, git_repo_factory) -> Path:
    """A repo at the path the hook computes from a patched HOME."""
    repo = tmp_path / "Documents" / "Projects" / "claude-config"
    repo.parent.mkdir(parents=True)
    git_repo_factory(repo)
    return repo


@pytest.fixture
def git_repo_factory():
    """A repo at an arbitrary path, seeded with one commit.

    conftest's `git_repo` fixture is fixed to tmp_path; these tests need the
    repo at the specific location master_repo() resolves to, and a second one
    beside it for the sibling-directory case. Only the path varies, so the git
    invocation itself comes from conftest.
    """

    def make(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        run_git(path, "init", "-q", "-b", "main", ".")
        run_git(path, "config", "user.email", "test@example.invalid")
        run_git(path, "config", "user.name", "test")
        (path / "README.md").write_text("seed\n")
        run_git(path, "add", "README.md")
        run_git(path, "commit", "-qm", "seed")
        return path

    return make


def commit(repo: Path, relative: str, body: str = "x\n") -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    run_git(repo, "add", relative)
    run_git(repo, "commit", "-qm", f"touch {relative}")


def run_hook(payload, home: Path, repo: Path | None = None) -> str:
    env = {**os.environ, "HOME": str(home)}
    env["CLAUDE_CONFIG_REPO"] = str(
        repo if repo else home / "Documents/Projects/claude-config"
    )
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def payload(repo: Path, command: str = "git commit -m x") -> dict:
    return {"tool_input": {"command": command}, "cwd": str(repo)}


def fired(out: str) -> bool:
    if not out:
        return False
    data = json.loads(out)
    block = data["hookSpecificOutput"]
    assert block["hookEventName"] == "PostToolUse"
    assert block["additionalContext"]
    return True


class TestFiring:
    @pytest.mark.parametrize(
        "relative",
        ["skills/x/SKILL.md", "scripts/x.py", "hooks/x.py", "CLAUDE.md"],
    )
    def test_commit_touching_a_config_asset_records_and_injects(
        self, fake_master, tmp_path, relative
    ):
        commit(fake_master, relative)
        assert fired(run_hook(payload(fake_master), tmp_path))
        assert relative in (fake_master / MARKER).read_text()

    @pytest.mark.parametrize("relative", ["docs/note.md", "pixi.lock", "README.md"])
    def test_commit_touching_nothing_auditable_is_silent(
        self, fake_master, tmp_path, relative
    ):
        commit(fake_master, relative)
        assert run_hook(payload(fake_master), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_non_commit_bash_is_silent(self, fake_master, tmp_path):
        commit(fake_master, "scripts/x.py")
        out = run_hook(payload(fake_master, command="git status"), tmp_path)
        assert out == ""
        assert not (fake_master / MARKER).exists()

    def test_commit_outside_the_master_repo_is_silent(
        self, fake_master, tmp_path, git_repo_factory
    ):
        """The config asset is committed in the master repo *and* the cwd points
        elsewhere. An earlier version of this test left the master repo's HEAD
        holding only the seed commit, so it passed whether or not the hook
        looked at cwd at all -- and a rewrite that deleted the cwd guard kept
        it green."""
        commit(fake_master, "scripts/x.py")
        other = git_repo_factory(tmp_path / "Documents" / "Projects" / "other")
        commit(other, "docs/note.md")
        assert run_hook(payload(other), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_a_sibling_directory_is_not_the_master_repo(
        self, fake_master, tmp_path, git_repo_factory
    ):
        """A bare prefix test would swallow claude-config-other."""
        commit(fake_master, "scripts/x.py")
        sibling = git_repo_factory(
            tmp_path / "Documents" / "Projects" / "claude-config-other"
        )
        commit(sibling, "scripts/y.py")
        assert run_hook(payload(sibling), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_clearing_then_committing_elsewhere_does_not_re_arm(
        self, fake_master, tmp_path, git_repo_factory
    ):
        """The concrete consequence of the missing guard: finish the audit,
        clear the marker, commit in any other project, and the marker came
        back -- the standing warning this design exists to prevent."""
        commit(fake_master, "scripts/x.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        (fake_master / MARKER).unlink()
        other = git_repo_factory(tmp_path / "Documents" / "Projects" / "other")
        commit(other, "docs/note.md")
        assert run_hook(payload(other), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_a_subdirectory_of_the_master_repo_still_fires(self, fake_master, tmp_path):
        commit(fake_master, "scripts/x.py")
        (fake_master / "scripts").mkdir(exist_ok=True)
        out = run_hook(
            {
                "tool_input": {"command": "git commit -m x"},
                "cwd": str(fake_master / "scripts"),
            },
            tmp_path,
        )
        assert fired(out)

    @pytest.mark.parametrize("bad", ["", "not json", "[]", "null"])
    def test_malformed_stdin_is_silent(self, fake_master, tmp_path, bad):
        assert run_hook(bad, tmp_path) == ""

    def test_missing_cwd_is_silent(self, fake_master, tmp_path):
        commit(fake_master, "scripts/x.py")
        assert run_hook({"tool_input": {"command": "git commit"}}, tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_missing_tool_input_is_silent(self, fake_master, tmp_path):
        assert run_hook({"cwd": str(fake_master)}, tmp_path) == ""


class TestIdempotence:
    def test_second_commit_adding_no_new_asset_injects_nothing(
        self, fake_master, tmp_path
    ):
        commit(fake_master, "scripts/x.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        commit(fake_master, "scripts/x.py", body="changed\n")
        assert run_hook(payload(fake_master), tmp_path) == ""

    def test_second_commit_adding_a_new_asset_injects_again(
        self, fake_master, tmp_path
    ):
        commit(fake_master, "scripts/x.py")
        run_hook(payload(fake_master), tmp_path)
        commit(fake_master, "hooks/y.py")
        assert fired(run_hook(payload(fake_master), tmp_path))

    def test_the_marker_accumulates_a_sorted_unique_set(self, fake_master, tmp_path):
        for relative in ("scripts/x.py", "hooks/y.py", "CLAUDE.md"):
            commit(fake_master, relative)
            run_hook(payload(fake_master), tmp_path)
        lines = (fake_master / MARKER).read_text().splitlines()
        assert lines == sorted(set(lines))
        assert [line.split("\t")[1] for line in lines] == [
            "CLAUDE.md",
            "hooks/y.py",
            "scripts/x.py",
        ]
        assert {line.split("\t")[0] for line in lines} == {"main"}


class TestBranchScoping:
    """The obligation is an audit for what *this* branch changed. Unscoped, the
    warning follows you to an unrelated branch and clearing it there discards
    the original branch's obligation."""

    def test_another_branch_entry_is_not_reported_as_this_branch_s(
        self, fake_master, tmp_path
    ):
        commit(fake_master, "scripts/x.py")
        run_hook(payload(fake_master), tmp_path)
        run_git(fake_master, "checkout", "-q", "-b", "other")
        commit(fake_master, "hooks/y.py")
        run_hook(payload(fake_master), tmp_path)
        lines = (fake_master / MARKER).read_text().splitlines()
        assert "main\tscripts/x.py" in lines
        assert "other\thooks/y.py" in lines

    def test_the_same_asset_on_a_second_branch_fires_again(self, fake_master, tmp_path):
        commit(fake_master, "scripts/x.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        run_git(fake_master, "checkout", "-q", "-b", "other")
        commit(fake_master, "scripts/x.py", body="changed\n")
        assert fired(run_hook(payload(fake_master), tmp_path))


class TestWiring:
    def test_the_hook_declares_its_event(self):
        assert "# claude-hook: PostToolUse Bash" in HOOK.read_text()

    def test_the_marker_is_gitignored(self):
        """A committed marker would follow the branch to another machine and
        claim an audit is owed there."""
        assert MARKER in (REPO_ROOT / ".gitignore").read_text().split()

    def test_the_expanduser_default_is_still_used_without_the_override(
        self, fake_master, tmp_path
    ):
        """The override exists for portability and for these tests; the
        documented install path must keep working without it."""
        commit(fake_master, "scripts/x.py")
        env = {**os.environ, "HOME": str(tmp_path)}
        env.pop("CLAUDE_CONFIG_REPO", None)
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(payload(fake_master)),
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        assert fired(result.stdout.strip())


class TestCommitActuallyHappened:
    """`git commit` in a command is not proof a commit succeeded, and this repo
    runs ruff with --exit-non-zero-on-fix, so a rejected-then-retried commit is
    routine rather than hypothetical."""

    def test_a_path_limited_commit_still_records(self, fake_master, tmp_path):
        """ "Is the index clean" was tried as a success proxy and rejected: this
        commit really did land a config asset while an unrelated file stayed
        staged, and that proxy dropped it."""
        (fake_master / "scripts").mkdir(exist_ok=True)
        (fake_master / "scripts" / "x.py").write_text("x\n")
        (fake_master / "other.txt").write_text("o\n")
        run_git(fake_master, "add", "scripts/x.py", "other.txt")
        run_git(fake_master, "commit", "-qm", "cfg", "--", "scripts/x.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        assert "scripts/x.py" in (fake_master / MARKER).read_text()

    def test_a_failed_retry_emits_nothing_because_the_asset_is_already_owed(
        self, fake_master, tmp_path
    ):
        """What replaces the dropped proxy. On a failed commit HEAD is the
        previous commit, whose assets are already recorded, so the idempotence
        check keeps the hook silent without needing to detect the failure."""
        commit(fake_master, "scripts/x.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        # HEAD unchanged, as after a rejected commit.
        assert run_hook(payload(fake_master), tmp_path) == ""

    def test_an_interrupted_response_records_nothing(self, fake_master, tmp_path):
        """`interrupted` is the one failure the Bash payload actually reports;
        it carries stdout/stderr and no exit status."""
        commit(fake_master, "scripts/x.py")
        data = {**payload(fake_master), "tool_response": {"interrupted": True}}
        assert run_hook(data, tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    @pytest.mark.parametrize(
        "response", [{"stdout": "1 file changed"}, {}, None, "text"]
    )
    def test_anything_not_known_to_have_failed_still_fires(
        self, fake_master, tmp_path, response
    ):
        """One-directional on purpose: an unrecognised payload degrades to
        recording rather than to silence."""
        commit(fake_master, "scripts/x.py")
        data = {**payload(fake_master), "tool_response": response}
        assert fired(run_hook(data, tmp_path))


class TestCommitShapes:
    def test_a_merge_commit_is_seen(self, fake_master, tmp_path):
        """How config assets usually reach the default branch. Without -m,
        diff-tree reports no paths for a merge at all."""
        run_git(fake_master, "checkout", "-q", "-b", "feat")
        commit(fake_master, "scripts/from_branch.py")
        run_git(fake_master, "checkout", "-q", "main")
        commit(fake_master, "docs/other.md")
        run_git(fake_master, "merge", "-q", "--no-ff", "feat", "-m", "merge")
        assert fired(run_hook(payload(fake_master), tmp_path))
        assert "scripts/from_branch.py" in (fake_master / MARKER).read_text()

    def test_a_root_commit_is_seen(self, tmp_path):
        """A parentless commit reports no paths without --root."""
        repo = tmp_path / "Documents" / "Projects" / "claude-config"
        repo.mkdir(parents=True)
        run_git(repo, "init", "-q", "-b", "main", ".")
        run_git(repo, "config", "user.email", "t@e.invalid")
        run_git(repo, "config", "user.name", "t")
        (repo / "CLAUDE.md").write_text("x\n")
        run_git(repo, "add", "CLAUDE.md")
        run_git(repo, "commit", "-qm", "root")
        assert fired(run_hook(payload(repo), tmp_path))


class TestLegacyMarker:
    """A marker written before branch scoping existed holds unscoped lines."""

    def test_an_asset_recorded_both_ways_is_listed_once(self, fake_master, tmp_path):
        """Found in production: the hook reported the same path to itself
        twice, once from the legacy line and once from the scoped one."""
        (fake_master / MARKER).write_text("scripts/x.py\n")
        commit(fake_master, "scripts/x.py")
        out = run_hook(payload(fake_master), tmp_path)
        assert fired(out)
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        assert context.count("scripts/x.py") == 1
        assert "1 claude-config asset(s)" in context

    def test_an_unscoped_line_still_counts_as_owed(self, fake_master, tmp_path):
        """The safe reading of an obligation with no recorded owner is that it
        is still owed, so it is not silently dropped."""
        (fake_master / MARKER).write_text("hooks/legacy.py\n")
        commit(fake_master, "scripts/x.py")
        out = run_hook(payload(fake_master), tmp_path)
        assert (
            "hooks/legacy.py"
            in json.loads(out)["hookSpecificOutput"]["additionalContext"]
        )
