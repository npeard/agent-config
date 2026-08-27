"""End-to-end tests for install.sh, run against a throwaway HOME.

install.sh is the single documented entry point for a new machine and had no
tests at all, which is how four defects accumulated in it -- including one
that aborted a genuinely fresh install on its first command. Every case here
runs the real script with HOME pointed at a temp directory, because the
defects were in the script's interaction with the filesystem rather than in
anything a unit could observe.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL = REPO_ROOT / "install.sh"


def install(home: Path) -> subprocess.CompletedProcess[str]:
    """Run install.sh with HOME redirected at `home`.

    The assertion is not paranoia for its own sake: this script rewrites
    ~/.claude, so a test that leaked the real HOME would rewrite the
    machine's live configuration rather than fail.
    """
    assert home.resolve() != Path.home().resolve()
    return subprocess.run(
        [str(INSTALL)],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
        text=True,
        check=False,
    )


def skill_names() -> list[str]:
    return sorted(p.name for p in (REPO_ROOT / "skills").iterdir() if p.is_dir())


class TestFreshMachine:
    """The documented new-machine path: nothing under HOME yet."""

    def test_a_fresh_home_is_installed_from_nothing(self, tmp_path: Path):
        """install.sh linked into $HOME/.claude before creating it, so under
        `set -e` the one documented command for a new machine died on its
        first line -- before the env was materialized or hooks registered."""
        result = install(tmp_path)
        assert result.returncode == 0, result.stderr
        claude = tmp_path / ".claude"
        assert (claude / "CLAUDE.md").resolve() == (REPO_ROOT / "CLAUDE.md").resolve()
        for name in skill_names():
            assert (claude / "skills" / name).resolve() == (
                REPO_ROOT / "skills" / name
            ).resolve()
        # A new machine has no settings.json, and registration used to report
        # "nothing to do" for that case: the install said success and left the
        # machine with no hooks at all.
        hooks = json.loads((claude / "settings.json").read_text())["hooks"]
        assert hooks
        assert all(
            any(str(REPO_ROOT / "hooks") in h["command"] for h in entry["hooks"])
            for entries in hooks.values()
            for entry in entries
        )

    def test_rerunning_is_safe(self, tmp_path: Path):
        assert install(tmp_path).returncode == 0
        second = install(tmp_path)
        assert second.returncode == 0, second.stderr
        claude = tmp_path / ".claude"
        assert (claude / "CLAUDE.md").is_symlink()
        assert sorted(p.name for p in (claude / "skills").iterdir()) == skill_names()


class TestBackups:
    def test_a_second_run_keeps_the_first_backup(self, tmp_path: Path):
        """Both install.sh and register_hooks.py wrote a fixed `.bak`, so
        re-running replaced the only copy of the previous state; ~/.claude had
        already accumulated three backups of a single generation."""
        claude = tmp_path / ".claude"
        claude.mkdir()
        for content in ("first", "second"):
            (claude / "CLAUDE.md").unlink(missing_ok=True)
            (claude / "CLAUDE.md").write_text(content)
            assert install(tmp_path).returncode == 0
        saved = sorted(p.read_text() for p in claude.glob("CLAUDE.md.*"))
        assert saved == ["first", "second"]


class TestSkillLinks:
    def test_a_link_to_a_removed_skill_is_pruned(self, tmp_path: Path):
        """A renamed or deleted skill left its link behind, and a stale link
        in ~/.claude/skills is offered to every session as a real skill."""
        skills = tmp_path / ".claude" / "skills"
        skills.mkdir(parents=True)
        stale = skills / "renamed-away"
        stale.symlink_to(REPO_ROOT / "skills" / "renamed-away")
        foreign = skills / "another-tools-skill"
        foreign.symlink_to(tmp_path / "nowhere")
        assert install(tmp_path).returncode == 0
        assert not stale.is_symlink()
        # Only links into this repo are ours to remove; another tool's are not.
        assert foreign.is_symlink()

    def test_live_skill_links_survive_pruning(self, tmp_path: Path):
        assert install(tmp_path).returncode == 0
        assert install(tmp_path).returncode == 0
        skills = tmp_path / ".claude" / "skills"
        assert sorted(p.name for p in skills.iterdir()) == skill_names()
