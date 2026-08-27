"""The platform seam.

Junctions, not symlinks, are how Windows links a directory without
Developer Mode or elevation. Git Bash's `ln -s` does not fail on such a
machine -- it silently deep-copies -- so linking is verified, never
trusted, and verify_link() is the guard that catches the copy.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "platform_paths", REPO / "scripts" / "platform_paths.py"
)
platform_paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform_paths)


class TestInterpreter:
    def test_names_this_platforms_layout(self):
        got = platform_paths.interpreter(Path("/repo"))
        if os.name == "nt":
            assert got.name == "python.exe"
            assert got.parent.name == "dev"
        else:
            assert got.name == "python"
            assert got.parent.name == "bin"

    def test_is_under_the_dev_env(self):
        got = platform_paths.interpreter(Path("/repo"))
        assert ".pixi" in got.parts and "envs" in got.parts and "dev" in got.parts


class TestLinkDir:
    def test_a_link_reads_through_to_the_source(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("hello", encoding="utf-8")
        dest = tmp_path / "dest"
        platform_paths.link_dir(src, dest)
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == "hello"

    def test_an_edit_at_the_source_is_seen_through_the_link(self, tmp_path):
        # The property that distinguishes a link from a copy, which is the
        # whole point: a copy would still read "before".
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("before", encoding="utf-8")
        dest = tmp_path / "dest"
        platform_paths.link_dir(src, dest)
        (src / "SKILL.md").write_text("after", encoding="utf-8")
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == "after"

    def test_is_link_and_target_agree_with_what_was_made(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        platform_paths.link_dir(src, dest)
        assert platform_paths.is_link(dest)
        assert platform_paths.link_target(dest) == src.resolve()

    def test_a_plain_directory_is_not_a_link(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert not platform_paths.is_link(plain)
        assert platform_paths.link_target(plain) is None


class TestVerifyLink:
    def test_a_real_link_into_the_repo_verifies(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / "skills" / "one").mkdir(parents=True)
        dest = tmp_path / "installed"
        platform_paths.link_dir(repo / "skills" / "one", dest)
        assert platform_paths.verify_link(dest, repo)

    def test_a_copy_is_refused(self, tmp_path):
        # Exactly what Git Bash's `ln -s` silently produces on a machine
        # without Developer Mode. It must not read as a successful install.
        import shutil

        repo = tmp_path / "repo"
        (repo / "skills" / "one").mkdir(parents=True)
        dest = tmp_path / "installed"
        shutil.copytree(repo / "skills" / "one", dest)
        assert not platform_paths.verify_link(dest, repo)

    def test_a_link_pointing_outside_the_repo_is_refused(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        dest = tmp_path / "installed"
        platform_paths.link_dir(elsewhere, dest)
        assert not platform_paths.verify_link(dest, repo)

    def test_a_missing_path_is_refused(self, tmp_path):
        assert not platform_paths.verify_link(tmp_path / "nope", tmp_path)
