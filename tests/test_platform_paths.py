"""The platform seam.

Junctions, not symlinks, are how Windows links a directory without
Developer Mode or elevation. Git Bash's `ln -s` does not fail on such a
machine -- it silently deep-copies -- so linking is verified, never
trusted, and verify_link() is the guard that catches the copy.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

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

    def test_the_per_platform_forms_do_not_depend_on_the_running_host(self):
        """Both are needed at once when writing a config that names the two
        platforms in one entry, so neither may consult os.name."""
        windows = platform_paths.windows_interpreter(Path("/repo"))
        posix = platform_paths.posix_interpreter(Path("/repo"))
        assert windows.name == "python.exe"
        assert windows.parent.name == "dev"
        assert posix.name == "python"
        assert posix.parent.name == "bin"
        assert windows != posix

    def test_the_live_form_is_one_of_the_two_per_platform_forms(self):
        """Keeps interpreter() a selection between the layouts above rather
        than a third, independently drifting spelling of the same path."""
        repo = Path("/repo")
        assert platform_paths.interpreter(repo) in (
            platform_paths.windows_interpreter(repo),
            platform_paths.posix_interpreter(repo),
        )


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

    def test_a_relative_target_resolves_against_the_link_not_the_cwd(
        self, tmp_path, monkeypatch
    ):
        """Latent today -- link_dir() writes absolute targets -- but a link
        made by hand or by another tool can be relative, and the OS follows
        one relative to the link's own directory. Anchoring it to the process
        cwd instead made the same link read differently depending on where
        preflight was invoked from, so a good link could be called a copy.
        """
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"
        try:
            dest.symlink_to(Path("src"), target_is_directory=True)
        except OSError:
            # Windows without Developer Mode: os.symlink raises WinError 1314,
            # and a junction cannot hold a relative target at all.
            pytest.skip("this platform cannot create a relative symlink")
        # Somewhere with no "src" of its own, so a cwd-anchored resolve
        # produces a path that does not exist rather than a different one.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        assert platform_paths.link_target(dest) == src.resolve()

    def test_a_plain_directory_is_not_a_link(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        assert not platform_paths.is_link(plain)
        assert platform_paths.link_target(plain) is None

    @pytest.mark.skipif(os.name != "nt", reason="exercises the mklink guard")
    def test_a_reported_success_that_is_not_a_link_still_raises(
        self, tmp_path, monkeypatch
    ):
        # mklink returning 0 is not proof of a link: this is the scenario
        # verify_link() exists to catch after the fact, and link_dir() must
        # refuse to report success for it in the first place.
        src = tmp_path / "src"
        src.mkdir()
        dest = tmp_path / "dest"

        def fake_run(*args, **kwargs):
            dest.mkdir()  # a plain directory, not a junction
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(platform_paths.subprocess, "run", fake_run)
        with pytest.raises(OSError):
            platform_paths.link_dir(src, dest)


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
