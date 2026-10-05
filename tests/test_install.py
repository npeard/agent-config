"""install.py, driven against a temp HOME.

Never the real ~/.claude: these tests move files aside and delete links.
Most pass --skip-env, which stops before the pixi step; the one case that
does not stubs that step rather than materializing an environment, and
redirects hook registration at a settings file under the temp home.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import preflight
import pytest
from conftest import run_git

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install", REPO / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

import platform_paths_helper as pp  # provided by conftest; see Step 2


def run(home: Path) -> int:
    return install.main(["--home", str(home), "--skip-env"])


def skill_destinations(home: Path) -> tuple[Path, Path]:
    return home / ".claude" / "skills", home / ".agents" / "skills"


class TestFreshMachine:
    def test_a_fresh_home_gets_both_instruction_adapters(self, tmp_path):
        assert run(tmp_path) == 0
        claude = tmp_path / ".claude" / "CLAUDE.md"
        codex = tmp_path / ".codex" / "AGENTS.md"
        source = REPO / "AGENTS.md"
        assert claude.read_text(encoding="utf-8") == f"@{source.as_posix()}\n"
        header, guidance = codex.read_text(encoding="utf-8").split("\n\n", 1)
        assert header == (
            f"<!-- Generated from {source.as_posix()}; "
            "rerun this repository's installer to refresh. -->"
        )
        assert guidance == source.read_text(encoding="utf-8")
        # A stub, not a link: it needs no privilege on any platform.
        assert not pp.is_link(claude)

    def test_instruction_adapters_are_idempotent(self, tmp_path):
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        assert not list((tmp_path / ".claude").glob("CLAUDE.md.*.bak"))
        assert not list((tmp_path / ".codex").glob("AGENTS.md.*.bak"))

    def test_every_skill_is_linked_for_both_hosts(self, tmp_path):
        assert run(tmp_path) == 0
        for installed in skill_destinations(tmp_path):
            for src in sorted((REPO / "skills").iterdir()):
                if src.is_dir():
                    assert pp.verify_link(installed / src.name, REPO)

    def test_rerunning_writes_no_skill_backup_for_either_host(self, tmp_path):
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        for installed in skill_destinations(tmp_path):
            assert not list(installed.glob("*.bak"))


@pytest.mark.parametrize("changed_guidance", [False, True])
def test_main_checkout_adapters_are_current_in_a_linked_worktree(
    git_repo, monkeypatch, changed_guidance
):
    (git_repo / "install.py").write_text("", encoding="utf-8")
    (git_repo / "AGENTS.md").write_text("installed guidance\n", encoding="utf-8")
    run_git(git_repo, "add", "install.py", "AGENTS.md")
    run_git(git_repo, "commit", "-qm", "installation sources")
    worktree = git_repo / "linked worktree"
    run_git(git_repo, "worktree", "add", "-q", "-b", "feature", str(worktree))
    home = git_repo / "home"
    monkeypatch.setattr(install, "REPO", git_repo)
    install.install_instructions(home)
    if changed_guidance:
        (worktree / "AGENTS.md").write_text(
            "uninstalled branch edit\n", encoding="utf-8"
        )
    monkeypatch.chdir(worktree)
    report = preflight.Report()
    preflight.check_instructions(report, worktree, home)
    assert [row[:2] for row in report.rows] == [
        (preflight.OK, "Claude instructions"),
        (preflight.OK, "Codex instructions"),
    ]


class TestEnvironmentAndHookRegistration:
    """The half of main() that --skip-env returns before reaching.

    install.py's docstring calls its ordering load-bearing: the pixi
    environment must exist before hooks are registered, because a registered
    hook names that environment's interpreter in its command. Every other test
    here passes --skip-env and so asserts nothing about it. The step that is
    genuinely expensive is `pixi install`, so that one is stubbed and the
    registration it gates is run for real -- against a settings file under the
    temp home, never ~/.claude/settings.json.
    """

    def run_with_stubbed_env(self, home: Path, monkeypatch) -> tuple[int, list[str]]:
        """(exit code, order the two steps ran in) for a full install."""
        order: list[str] = []

        def fake_materialize() -> int:
            order.append("env")
            return 0

        real_run = subprocess.run

        def run(argv, **kwargs):
            # install.subprocess and platform_paths.subprocess are the same
            # module object, so this also sees link_dir's mklink calls on
            # Windows. Only the registration is redirected; everything else
            # is passed straight through.
            registrars = {
                str(REPO / "scripts" / "register_hooks.py"): "claude-register",
                str(REPO / "scripts" / "register_codex_hooks.py"): "codex-register",
            }
            registrar = next(
                (name for path, name in registrars.items() if path in argv), None
            )
            if registrar is None:
                return real_run(argv, **kwargs)
            order.append(registrar)
            # install.py must pass --settings under --home itself; the
            # registrars' default is the real home. Refuse rather than run,
            # so a regression fails here instead of writing ~/.claude.
            settings = (
                home / ".claude" / "settings.json"
                if registrar == "claude-register"
                else home / ".codex" / "hooks.json"
            )
            assert argv[-2:] == ["--settings", str(settings)], argv
            return real_run(argv, **kwargs)

        monkeypatch.setattr(install, "materialize_env", fake_materialize)
        monkeypatch.setattr(install.subprocess, "run", run)
        # The interpreter guard between the two steps is a real existence
        # check against this repo's own dev environment, which is what is
        # running these tests, so it needs no stub.
        return install.main(["--home", str(home)]), order

    def test_the_env_is_materialized_before_hooks_are_registered(
        self, tmp_path, monkeypatch
    ):
        """A registered hook names the dev interpreter in its command, so
        registering first writes hooks that cannot start -- while reporting
        success, which is what an earlier version did."""
        code, order = self.run_with_stubbed_env(tmp_path, monkeypatch)
        assert code == 0
        assert order == ["env", "claude-register", "codex-register"]

    def test_a_fresh_home_ends_up_with_hooks_pointing_into_this_repo(
        self, tmp_path, monkeypatch
    ):
        """A new machine has no settings.json, and registration used to report
        "nothing to do" for that case: the install said success and left the
        machine with no hooks at all."""
        code, _ = self.run_with_stubbed_env(tmp_path, monkeypatch)
        assert code == 0
        hooks = json.loads(
            (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
        )["hooks"]
        assert hooks
        entries = [
            h for group in hooks.values() for entry in group for h in entry["hooks"]
        ]
        assert entries
        for h in entries:
            # The interpreter is the command and the hook file is its
            # argument, which is the ordering install.py exists to guarantee:
            # a hook naming an interpreter that does not exist is silently
            # dead, so both halves are asserted, not just that a row is there.
            assert h["command"] == str(install.platform_paths.interpreter(REPO))
            assert any(str(REPO / "hooks") in arg for arg in h["args"])

    def test_a_fresh_home_ends_up_with_codex_hooks_pointing_into_this_repo(
        self, tmp_path, monkeypatch
    ):
        """A successful install used to configure only Claude, silently leaving
        Codex without the lifecycle hooks this repository carries."""
        code, _ = self.run_with_stubbed_env(tmp_path, monkeypatch)
        assert code == 0
        hooks = json.loads(
            (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        entries = [
            handler
            for groups in hooks.values()
            for group in groups
            for handler in group["hooks"]
        ]
        assert entries
        for handler in entries:
            assert str(REPO / "hooks") in handler["command"]

    def test_a_failed_env_stops_before_registering_anything(
        self, tmp_path, monkeypatch
    ):
        """The ordering only buys anything if the failure stops the sequence;
        registering after a failed `pixi install` is the exact case that
        writes hooks naming an interpreter that is not there."""
        ran: list[str] = []
        real_run = subprocess.run

        def run(argv, **kwargs):
            if str(REPO / "scripts" / "register_hooks.py") in argv:
                ran.append("register")
                raise AssertionError("registered after a failed environment step")
            return real_run(argv, **kwargs)

        monkeypatch.setattr(install, "materialize_env", lambda: 1)
        monkeypatch.setattr(install.subprocess, "run", run)
        assert install.main(["--home", str(tmp_path)]) == 1
        assert ran == []
        assert not (tmp_path / ".claude" / "settings.json").exists()


class TestBackups:
    @pytest.mark.parametrize("relative", [".claude/CLAUDE.md", ".codex/AGENTS.md"])
    def test_invalid_utf8_adapter_is_backed_up_and_repaired(self, tmp_path, relative):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True)
        original = b"user data\xff\xfe\x00\r\n"
        dest.write_bytes(original)
        assert run(tmp_path) == 0
        backups = list(dest.parent.glob(f"{dest.name}.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original
        assert "AGENTS.md" in dest.read_text(encoding="utf-8")
        assert run(tmp_path) == 0
        assert list(dest.parent.glob(f"{dest.name}.*.bak")) == backups

    @pytest.mark.parametrize(
        ("relative", "name"),
        [(Path(".claude"), "CLAUDE.md"), (Path(".codex"), "AGENTS.md")],
    )
    def test_conflicting_instruction_file_is_backed_up(self, tmp_path, relative, name):
        directory = tmp_path / relative
        directory.mkdir()
        (directory / name).write_text("mine", encoding="utf-8")
        assert run(tmp_path) == 0
        backups = list(directory.glob(f"{name}.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "mine"

    def test_an_existing_regular_file_is_backed_up(self, tmp_path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "CLAUDE.md").write_text("mine", encoding="utf-8")
        assert run(tmp_path) == 0
        backups = list(claude.glob("CLAUDE.md.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "mine"

    def test_a_second_run_keeps_the_first_backup(self, tmp_path):
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "CLAUDE.md").write_text("first", encoding="utf-8")
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        backups = list(claude.glob("CLAUDE.md.*.bak"))
        # The stub the first run wrote is identical to what the second would
        # write, so the second must not churn another backup.
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == "first"

    def test_a_directory_at_the_claude_md_path_is_backed_up(self, tmp_path):
        # install.sh tested `-e`, which matches a directory; the port tested
        # is_file() and rmtree'd anything else, destroying it unrecoverably.
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "CLAUDE.md").mkdir()
        (claude / "CLAUDE.md" / "important.txt").write_text("mine", encoding="utf-8")
        assert run(tmp_path) == 0
        backups = list(claude.glob("CLAUDE.md.*.bak"))
        assert len(backups) == 1
        assert (backups[0] / "important.txt").read_text(encoding="utf-8") == "mine"
        assert (claude / "CLAUDE.md").is_file()

    @pytest.mark.parametrize("skills", [".claude/skills", ".agents/skills"])
    def test_a_real_directory_at_a_skill_path_is_backed_up(self, tmp_path, skills):
        skills = tmp_path / skills
        skills.mkdir(parents=True)
        name = next(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
        (skills / name).mkdir()
        (skills / name / "MY_WORK.md").write_text("mine", encoding="utf-8")
        assert run(tmp_path) == 0
        backups = list(skills.glob(f"{name}.*.bak"))
        assert len(backups) == 1
        assert (backups[0] / "MY_WORK.md").read_text(encoding="utf-8") == "mine"
        assert pp.verify_link(skills / name, REPO)

    def test_a_correct_install_rerun_writes_no_skill_backup(self, tmp_path):
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        for skills in skill_destinations(tmp_path):
            assert not list(skills.glob("*.bak"))


class TestRepoLink:
    """~/.agents/agent-config is how hooks and prose find the checkout."""

    def link(self, home):
        return install.installation_contract.repo_link(home)

    def test_the_link_names_this_checkout(self, tmp_path):
        assert run(tmp_path) == 0
        assert pp.link_target(self.link(tmp_path)) == REPO.resolve()

    def test_rerunning_is_idempotent(self, tmp_path):
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        assert not list(self.link(tmp_path).parent.glob("agent-config.*.bak"))

    def test_a_stale_link_is_replaced(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        self.link(tmp_path).parent.mkdir(parents=True)
        pp.link_dir(elsewhere, self.link(tmp_path))
        assert run(tmp_path) == 0
        assert pp.link_target(self.link(tmp_path)) == REPO.resolve()
        assert elsewhere.is_dir()

    def test_a_real_directory_is_backed_up_not_destroyed(self, tmp_path):
        dest = self.link(tmp_path)
        dest.mkdir(parents=True)
        (dest / "mine.txt").write_text("mine", encoding="utf-8")
        assert run(tmp_path) == 0
        (backup,) = dest.parent.glob("agent-config.*.bak")
        assert (backup / "mine.txt").read_text(encoding="utf-8") == "mine"
        assert pp.link_target(dest) == REPO.resolve()


class TestSkillLinks:
    def test_a_stale_repo_link_is_pruned_from_both_hosts(self, tmp_path):
        assert run(tmp_path) == 0
        ghost = REPO / "skills" / "was-deleted"
        ghost.mkdir()
        try:
            for installed in skill_destinations(tmp_path):
                pp.link_dir(ghost, installed / ghost.name)
        finally:
            ghost.rmdir()
        assert run(tmp_path) == 0
        assert all(
            not (installed / ghost.name).exists()
            for installed in skill_destinations(tmp_path)
        )

    @pytest.mark.parametrize("installed", [".claude/skills", ".agents/skills"])
    def test_a_foreign_link_is_left_alone(self, tmp_path, installed):
        # Only links into this repo are ours to prune.
        assert run(tmp_path) == 0
        skills = tmp_path / installed
        other = tmp_path / "other-tool"
        other.mkdir()
        pp.link_dir(other, skills / "foreign")
        assert run(tmp_path) == 0
        assert (skills / "foreign").exists()


class TestCopyDetection:
    @pytest.mark.parametrize("installed", [".claude/skills", ".agents/skills"])
    def test_a_copy_left_by_a_previous_bad_install_is_replaced(
        self, tmp_path, installed
    ):
        # Git Bash's `ln -s` deep-copies on a machine without Developer Mode,
        # so a previously "successful" install can leave copies behind. They
        # must be repaired, not accepted.
        import shutil

        skills = tmp_path / installed
        skills.mkdir(parents=True)
        name = next(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
        shutil.copytree(REPO / "skills" / name, skills / name)
        assert run(tmp_path) == 0
        assert pp.verify_link(skills / name, REPO)
