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
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import run_git

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "audit-owed.py"
MARKER = ".audit-owed"
# What os.path.expanduser reads for "~" on this platform. Only the one test
# that exercises the un-overridden default needs it; everywhere else
# CLAUDE_CONFIG_REPO names the fixture outright, which is why the hook has no
# second override to keep in step.
HOME_VAR = "USERPROFILE" if os.name == "nt" else "HOME"


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
    # CLAUDE_CONFIG_REPO names the fixture outright rather than steering the
    # hook through a patched home. The hook resolves "~" with expanduser,
    # whose variable differs by platform, so a home patch would be one more
    # thing to keep in step for no gain.
    env = {**os.environ}
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

    def test_the_marker_accumulates_a_unique_set(self, fake_master, tmp_path):
        """Uniqueness is the property that matters; line order is not.

        Both readers -- this hook and audit_assets.owed_assets -- build a set
        and sort at the point of display, so nothing depends on the file being
        sorted on disk. It is asserted no longer because keeping it would mean
        rewriting the whole file on every commit, which is what lost a
        concurrent agent's entries.
        """
        for relative in ("scripts/x.py", "hooks/y.py", "CLAUDE.md"):
            commit(fake_master, relative)
            run_hook(payload(fake_master), tmp_path)
        lines = (fake_master / MARKER).read_text().splitlines()
        assert len(lines) == len(set(lines))
        assert set(lines) == {
            "main\tCLAUDE.md",
            "main\thooks/y.py",
            "main\tscripts/x.py",
        }


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
        documented install path must keep working without it.

        The home variable is set the way expanduser reads it on this platform
        -- USERPROFILE on Windows, HOME elsewhere. master_repo() deliberately
        does not substitute HOME itself: Git Bash exports it, sometimes in
        POSIX form or on a mapped drive, and preferring it there made the
        hook resolve to a directory that does not exist and never fire.
        """
        commit(fake_master, "scripts/x.py")
        env = {**os.environ, HOME_VAR: str(tmp_path)}
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

    @pytest.mark.skipif(
        os.name != "nt",
        reason="HOME is expanduser's own variable off Windows, so there is no "
        "second variable that could disagree with it.",
    )
    def test_a_git_bash_style_home_does_not_disable_the_hook(
        self, fake_master, tmp_path
    ):
        """Git Bash and MSYS2 export HOME, often in a form no Windows API can
        open ("/c/Users/npeard") or on a domain-mapped drive that differs from
        USERPROFILE. Preferring it over expanduser's own lookup made
        master_repo() name a nonexistent directory, and the hook silently
        never fired -- the exact failure its comment warns about. Whatever
        HOME says, USERPROFILE must decide.
        """
        commit(fake_master, "scripts/x.py")
        env = {**os.environ, HOME_VAR: str(tmp_path), "HOME": "/c/nonexistent"}
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


class TestCommandGate:
    """A substring test on "git commit" is not evidence a commit happened.

    The concrete consequence: immediately after `pixi run audit --clear-owed`
    on a branch whose HEAD touched an asset, any command merely quoting the
    phrase recreated the standing warning -- the nagging this whole design
    exists to avoid -- with nothing having been committed.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'git log --grep="git commit"',
            "git commit --dry-run",
            "git commit --dry-run -m x",
            'echo "remember to git commit"',
            "git status",
            "cat > note.txt <<EOF\ngit commit -m x\nEOF",
            "git log --oneline | grep 'git commit'",
        ],
    )
    def test_a_command_that_did_not_commit_is_silent(
        self, fake_master, tmp_path, command
    ):
        commit(fake_master, "scripts/x.py")
        (fake_master / MARKER).unlink(missing_ok=True)
        assert run_hook(payload(fake_master, command=command), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x",
            "git commit --amend --no-edit",
            "git commit -m 'git log --grep=x'",
            "git -C /somewhere commit -m x",
            "/usr/bin/git commit -m x",
            "git add -A && git commit -m x",
            "git add -A\ngit commit -m x",
            "cat > note.txt <<EOF\nhello\nEOF\ngit commit -am x",
            "git commit -n -m x",
        ],
    )
    def test_a_real_commit_still_fires(self, fake_master, tmp_path, command):
        commit(fake_master, "scripts/x.py")
        (fake_master / MARKER).unlink(missing_ok=True)
        assert fired(run_hook(payload(fake_master, command=command), tmp_path))

    def test_an_unbalanced_quote_no_longer_means_not_a_commit(
        self, fake_master, tmp_path
    ):
        """This test used to assert the opposite, and the assumption was wrong.
        `git commit -m "$(cat <<'EOF' ... EOF)"` is the message form CLAUDE.md
        mandates, and stripping its heredoc body leaves the opening line with
        an unbalanced quote -- so declining on one made the hook inert for the
        dominant commit form. Reporting on a commit that actually failed costs
        one marker entry, which the idempotence check below absorbs; missing
        every real commit cost the whole mechanism.
        """
        commit(fake_master, "scripts/x.py")
        out = run_hook(payload(fake_master, command="git commit -m 'oops"), tmp_path)
        assert fired(out)

    def test_the_mandated_co_authored_message_form_is_detected(
        self, fake_master, tmp_path
    ):
        commit(fake_master, "scripts/x.py")
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "feat: thing\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n"
            'EOF\n)"'
        )
        assert fired(run_hook(payload(fake_master, command=command), tmp_path))

    def test_a_herestring_does_not_swallow_the_command_after_it(
        self, fake_master, tmp_path
    ):
        """`<<<` is a herestring with no body. The heredoc regex matched at its
        second angle bracket, so everything after was discarded as body."""
        commit(fake_master, "scripts/x.py")
        command = "wc -l <<<hello\ngit commit -m x"
        assert fired(run_hook(payload(fake_master, command=command), tmp_path))

    def test_a_heredoc_body_mentioning_a_commit_is_still_silent(
        self, fake_master, tmp_path
    ):
        """The guard the above must not break: a body is data being written."""
        commit(fake_master, "scripts/x.py")
        (fake_master / MARKER).unlink(missing_ok=True)
        command = "cat > f.txt <<'EOF'\ngit commit -m x\nEOF"
        assert run_hook(payload(fake_master, command=command), tmp_path) == ""


class TestWorktrees:
    """`git worktree add ../wt` puts the checkout outside the main one.

    The cwd guard compared the payload's cwd against the master repo's path,
    so a sibling worktree failed it and the hook went silent -- while CLAUDE.md
    recommends worktrees for exactly the parallel-phase work most likely to
    change config assets. The branches this hook exists to catch armed nothing.
    """

    @pytest.fixture
    def worktree(self, fake_master, tmp_path):
        def make(repo: Path, name: str = "feat/x") -> Path:
            path = tmp_path / "worktrees" / name.replace("/", "-")
            run_git(repo, "worktree", "add", "-q", str(path), "-b", name)
            return path

        return make

    def test_a_commit_in_a_worktree_arms_the_main_checkout(
        self, fake_master, tmp_path, worktree
    ):
        tree = worktree(fake_master)
        commit(tree, "hooks/x.py")
        assert fired(run_hook(payload(tree), tmp_path))
        assert (fake_master / MARKER).read_text() == "feat/x\thooks/x.py\n"

    def test_the_marker_lands_in_the_main_checkout_not_the_worktree(
        self, fake_master, tmp_path, worktree
    ):
        """A worktree is deleted when its branch merges. An obligation recorded
        inside one dies with it, which is the opposite of why it is a file."""
        tree = worktree(fake_master)
        commit(tree, "scripts/x.py")
        assert fired(run_hook(payload(tree), tmp_path))
        assert not (tree / MARKER).exists()

    def test_a_worktree_of_an_unrelated_repo_is_still_silent(
        self, fake_master, tmp_path, git_repo_factory, worktree
    ):
        commit(fake_master, "scripts/x.py")
        other = git_repo_factory(tmp_path / "Documents" / "Projects" / "other")
        tree = worktree(other, name="other-branch")
        commit(tree, "scripts/y.py")
        assert run_hook(payload(tree), tmp_path) == ""
        assert not (fake_master / MARKER).exists()

    def test_a_cwd_that_is_not_a_git_repo_is_silent(self, fake_master, tmp_path):
        loose = tmp_path / "loose"
        loose.mkdir()
        commit(fake_master, "scripts/x.py")
        assert run_hook(payload(loose), tmp_path) == ""


class TestConcurrentWrites:
    """Two agents committing in one checkout must not lose each other's work.

    The marker was a read-modify-write: read the set, union, then
    `open(marker, "w")`. Whichever process wrote last wrote over the other's
    entry, and truncate-on-open meant a kill at the hook's 10s timeout left an
    empty file behind. Deterministic once the write is a single append, since
    an append cannot interleave and cannot truncate -- so this test can only
    fail against an implementation that reintroduces the race.
    """

    def test_existing_lines_are_preserved_verbatim(self, fake_master, tmp_path):
        """The deterministic half, and the mechanism the concurrent case needs.

        A rewrite normalizes the whole file, so lines it did not author come
        back reordered; an append cannot touch them. Seeded out of sorted
        order precisely so that a rewrite is visible without a race.
        """
        seeded = "zz/late\tscripts/z.py\naa/early\tscripts/a.py\n"
        (fake_master / MARKER).write_text(seeded)
        commit(fake_master, "hooks/new.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        assert (fake_master / MARKER).read_text() == seeded + "main\thooks/new.py\n"

    def test_a_marker_with_undecodable_bytes_does_not_crash(
        self, fake_master, tmp_path
    ):
        """Read in text mode, so one stray byte raised UnicodeDecodeError --
        a ValueError, not the OSError the read was guarding against."""
        (fake_master / MARKER).write_bytes(b"main\tscripts/old.py\n\xff\xfe\n")
        commit(fake_master, "hooks/new.py")
        assert fired(run_hook(payload(fake_master), tmp_path))
        assert b"hooks/new.py" in (fake_master / MARKER).read_bytes()

    def test_no_entry_is_lost_when_hooks_run_at_once(self, fake_master, tmp_path):
        count = 8
        trees = []
        for index in range(count):
            branch = f"feat/{index}"
            tree = tmp_path / "worktrees" / str(index)
            run_git(fake_master, "worktree", "add", "-q", str(tree), "-b", branch)
            commit(tree, f"hooks/h{index}.py")
            trees.append((branch, tree))

        # The race exists at any marker size; a large file only widens the
        # read-modify-write window from microseconds to milliseconds, so the
        # result is the mechanism rather than scheduler luck. At this size the
        # old implementation kept one entry in eight.
        (fake_master / MARKER).write_text(
            "".join(f"old/{n}\tskills/s{n}/SKILL.md\n" for n in range(50_000))
        )

        env = {**os.environ, "CLAUDE_CONFIG_REPO": str(fake_master)}
        # Started before any stdin is written, so all eight are already past
        # interpreter startup and blocked on the read when the payloads land.
        # Handing each its payload at spawn time would stagger them by the
        # startup cost, which is far longer than the window being tested.
        procs = [
            subprocess.Popen(
                [sys.executable, str(HOOK)],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            for _, _ in trees
        ]
        try:
            for proc, (_, tree) in zip(procs, trees):
                proc.stdin.write(json.dumps(payload(tree)))
            for proc in procs:
                proc.stdin.close()
            for proc in procs:
                assert proc.wait() == 0, proc.stderr.read()
        finally:
            # Popen does not close the pipes it opened, and eight leaked pairs
            # surface as PytestUnraisableExceptionWarning during collection of
            # some later test, which is a confusing place to debug from.
            for proc in procs:
                proc.__exit__(None, None, None)

        lines = set((fake_master / MARKER).read_text().splitlines())
        expected = {f"{branch}\thooks/h{i}.py" for i, (branch, _) in enumerate(trees)}
        assert expected <= lines


class TestTransientSpawnFailure:
    """The empty return conflated "no config assets" with "could not spawn
    git". The second silently forgets a real obligation, and it is what made
    this module fail three times under concurrent agent load while passing in
    isolation. Asserted structurally rather than by trying to reproduce the
    load."""

    def load_hook(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("audit_owed", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_transient_spawn_failure_is_retried(self, monkeypatch, git_repo):
        hook = self.load_hook()
        real = hook.subprocess.run
        calls = []

        def flaky(argv, **kwargs):
            calls.append(argv)
            if len(calls) == 1:
                raise OSError(35, "Resource temporarily unavailable")
            return real(argv, **kwargs)

        # Commit BEFORE patching: hook.subprocess is the shared module object,
        # so the patch reaches conftest's run_git too and would break the setup.
        commit(git_repo, "scripts/x.py")
        monkeypatch.setattr(hook.subprocess, "run", flaky)
        assert hook.committed_paths(str(git_repo)) == ["scripts/x.py"]
        assert len(calls) == 2

    def test_a_permanent_failure_still_declines(self, monkeypatch, git_repo):
        hook = self.load_hook()
        calls = []

        def always(argv, **kwargs):
            calls.append(argv)
            raise OSError(35, "Resource temporarily unavailable")

        monkeypatch.setattr(hook.subprocess, "run", always)
        assert hook.committed_paths(str(git_repo)) == []
        assert len(calls) == 2, "retried exactly once, not indefinitely"

    def test_the_retry_budget_fits_the_registered_hook_timeout(self):
        """register_hooks.py writes timeout: 10 for every hook. A killed hook
        loses every graceful path in this file, so the worst case -- one
        rev-parse plus two diff-tree attempts -- must stay under it."""
        source = HOOK.read_text()
        timeouts = [int(n) for n in re.findall(r"timeout=(\d+)", source)]
        assert timeouts, "no subprocess timeouts found"
        worst_case = timeouts[0] + 2 * timeouts[-1]
        assert worst_case < 10, f"worst case {worst_case}s exceeds the 10s budget"
