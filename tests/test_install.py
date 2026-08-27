"""install.py, driven against a temp HOME.

Never the real ~/.claude: these tests move files aside and delete links.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("install", REPO / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)

import platform_paths_helper as pp  # provided by conftest; see Step 2


def run(home: Path) -> int:
    return install.main(["--home", str(home), "--skip-env"])


class TestFreshMachine:
    def test_a_fresh_home_gets_a_claude_md_stub(self, tmp_path):
        assert run(tmp_path) == 0
        stub = tmp_path / ".claude" / "CLAUDE.md"
        assert stub.is_file()
        assert stub.read_text(encoding="utf-8").strip().startswith("@")
        # A stub, not a link: it needs no privilege on any platform.
        assert not pp.is_link(stub)

    def test_every_skill_is_linked_and_reads_through(self, tmp_path):
        assert run(tmp_path) == 0
        for src in sorted((REPO / "skills").iterdir()):
            if not src.is_dir():
                continue
            dest = tmp_path / ".claude" / "skills" / src.name
            assert dest.exists(), f"{src.name} not installed"
            assert pp.verify_link(dest, REPO), f"{src.name} is a copy, not a link"

    def test_rerunning_is_safe(self, tmp_path):
        assert run(tmp_path) == 0
        assert run(tmp_path) == 0
        for src in sorted((REPO / "skills").iterdir()):
            if src.is_dir():
                assert (tmp_path / ".claude" / "skills" / src.name).exists()


class TestBackups:
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

    def test_a_real_directory_at_a_skill_path_is_backed_up(self, tmp_path):
        skills = tmp_path / ".claude" / "skills"
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
        skills = tmp_path / ".claude" / "skills"
        assert not list(skills.glob("*.bak"))


class TestSkillLinks:
    def test_a_link_to_a_removed_skill_is_pruned(self, tmp_path):
        assert run(tmp_path) == 0
        skills = tmp_path / ".claude" / "skills"
        ghost = REPO / "skills" / "was-deleted"
        ghost.mkdir()
        try:
            pp.link_dir(ghost, skills / "was-deleted")
        finally:
            ghost.rmdir()
        assert run(tmp_path) == 0
        assert not (skills / "was-deleted").exists()

    def test_a_foreign_link_is_left_alone(self, tmp_path):
        # Only links into this repo are ours to prune.
        assert run(tmp_path) == 0
        skills = tmp_path / ".claude" / "skills"
        other = tmp_path / "other-tool"
        other.mkdir()
        pp.link_dir(other, skills / "foreign")
        assert run(tmp_path) == 0
        assert (skills / "foreign").exists()


class TestCopyDetection:
    def test_a_copy_left_by_a_previous_bad_install_is_replaced(self, tmp_path):
        # Git Bash's `ln -s` deep-copies on a machine without Developer Mode,
        # so a previously "successful" install can leave copies behind. They
        # must be repaired, not accepted.
        import shutil

        skills = tmp_path / ".claude" / "skills"
        skills.mkdir(parents=True)
        name = next(p.name for p in (REPO / "skills").iterdir() if p.is_dir())
        shutil.copytree(REPO / "skills" / name, skills / name)
        assert run(tmp_path) == 0
        assert pp.verify_link(skills / name, REPO)
