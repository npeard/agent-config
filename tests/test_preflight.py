"""Regression tests for scripts/preflight.py.

Every case here corresponds to a bug that actually shipped and was caught
in review, rather than to a restatement of the implementation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import platform_paths
import preflight
import pytest
from conftest import run_git

REPO_ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL = preflight.OK, preflight.WARN, preflight.FAIL


def statuses(report: preflight.Report, label: str) -> list[str]:
    return [s for s, lab, _ in report.rows if lab == label]


def details(report: preflight.Report, label: str) -> str:
    return " ".join(d for _, lab, d in report.rows if lab == label)


def isolate_preflight_home(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    home = root / "home"
    monkeypatch.setattr(preflight.Path, "home", lambda: home)
    return home


def forbidden(*args, **kwargs):
    raise AssertionError("a test reached the network, pixi or VS Code")


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch: pytest.MonkeyPatch):
    """main() now runs the dependency and extension checks, whose real
    effects are the network, pixi and `code`; no test may reach them."""
    monkeypatch.setattr(preflight.dep_updates, "live_fetch", forbidden)
    monkeypatch.setattr(preflight.dep_updates, "live_run", lambda root: forbidden)
    monkeypatch.setattr(preflight.vscode_extensions, "_run_code", lambda argv: None)


def dep_report(**changes):
    dep = preflight.dep_updates
    report = dep._blank(True, "win-64")
    for key, value in changes.items():
        setattr(report, key, value)
    return report


def torch_finding():
    return preflight.dep_updates.Finding(
        name="pytorch-gpu",
        pypi_name="torch",
        source="conda-forge",
        locked="2.13.0",
        candidate="2.14.0",
        candidate_source="pypi",
        wheel="win_amd64 cp313 wheel",
        spec=">=2.13",
        envs=["default"],
    )


class TestDetailLines:
    def test_lines_render_indented_under_their_row(self, capsys):
        report = preflight.Report()
        report.add(WARN, "dependency updates", "1 cross-source", lines=["a", "b"])
        report.add(OK, "next row")
        report.render()
        out = capsys.readouterr().out.splitlines()
        assert out[:4] == [
            "[warn] dependency updates: 1 cross-source",
            "  a",
            "  b",
            "[ok  ] next row",
        ]


class TestUpstream:
    """A branch whose upstream is a shared branch let a VS Code Sync push
    commits onto draft-august in two repos (doqs session 3d220b2c)."""

    @pytest.fixture
    def cloned(self, git_repo: Path, tmp_path: Path, monkeypatch) -> Path:
        remote = tmp_path / "remote.git"
        run_git(tmp_path, "init", "-q", "--bare", str(remote))
        run_git(git_repo, "remote", "add", "origin", str(remote))
        run_git(git_repo, "push", "-q", "origin", "main")
        run_git(git_repo, "branch", "-q", "draft-august")
        run_git(git_repo, "push", "-q", "origin", "draft-august")
        monkeypatch.chdir(git_repo)
        return git_repo

    def upstream(self) -> tuple[list[str], str]:
        report = preflight.Report()
        preflight.check_upstream(report)
        return statuses(report, "branch upstream"), details(report, "branch upstream")

    def test_same_name_is_ok(self, cloned: Path):
        run_git(cloned, "checkout", "-q", "-b", "feature")
        run_git(cloned, "push", "-q", "-u", "origin", "feature")
        assert self.upstream()[0] == [OK]

    def test_a_different_name_warns(self, cloned: Path):
        run_git(cloned, "checkout", "-q", "-b", "obc-direct", "origin/draft-august")
        status, detail = self.upstream()
        assert status == [WARN]
        assert "upstream is origin/draft-august" in detail
        assert "git branch --unset-upstream" in detail
        assert "git push -u origin HEAD" in detail

    def test_no_upstream_is_ok(self, cloned: Path):
        run_git(cloned, "checkout", "-q", "-b", "local-only")
        assert self.upstream()[0] == [OK]

    def test_detached_head_is_ok(self, cloned: Path):
        run_git(cloned, "checkout", "-q", "--detach")
        assert self.upstream()[0] == [OK]


class TestDependencies:
    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        (tmp_path / "pixi.toml").write_text("[workspace]\nname = 'p'\n")
        return tmp_path

    def test_findings_warn_with_detail_lines(self, project, monkeypatch):
        found = dep_report(cross_source=[torch_finding()])
        monkeypatch.setattr(preflight.dep_updates, "check", lambda *a, **k: found)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        assert statuses(report, "dependency updates (win-64)") == [WARN]
        assert any("pytorch-gpu -> torch" in line for line in report.lines[0])

    def test_clean_is_ok(self, project, monkeypatch):
        monkeypatch.setattr(
            preflight.dep_updates, "check", lambda *a, **k: dep_report()
        )
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        assert statuses(report, "dependency updates (win-64)") == [OK]

    def test_a_non_pixi_project_is_silent(self, tmp_path):
        report = preflight.Report()
        preflight.check_dependencies(report, tmp_path, offline=False)
        assert report.rows == []

    def test_pixi_missing_warns(self, project, monkeypatch):
        missing = dep_report(pixi_missing=True, platform="")
        monkeypatch.setattr(preflight.dep_updates, "check", lambda *a, **k: missing)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        assert [s for s, _, _ in report.rows] == [WARN]
        assert "pixi not found" in details(report, "dependency updates")

    def test_offline_reads_the_cache_and_never_fetches(self, project, monkeypatch):
        monkeypatch.setattr(preflight.dep_updates, "check", forbidden)
        found = dep_report(cross_source=[torch_finding()], from_cache=True)
        monkeypatch.setattr(preflight.dep_updates, "cached", lambda root, now: found)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=True)
        assert statuses(report, "dependency updates (win-64) (cached)") == [WARN]

    def hold_refresh_lock(self, project):
        # This test process is the live holder the real probe will find.
        lock = project / ".pixi" / "agent-drift" / "refresh.lock"
        lock.parent.mkdir(parents=True)
        lock.write_text(str(os.getpid()))

    def test_a_running_refresh_reports_the_cache_instead_of_computing(
        self, project, monkeypatch
    ):
        self.hold_refresh_lock(project)
        monkeypatch.setattr(preflight.dep_updates, "check", forbidden)
        found = dep_report(cross_source=[torch_finding()], from_cache=True)
        checked = time.mktime((2026, 9, 22, 12, 0, 0, 0, 0, -1))
        monkeypatch.setattr(
            preflight.dep_updates, "last_known", lambda root: (found, checked)
        )
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        label = "dependency updates (win-64) (as of 2026-09-22; refresh in progress)"
        assert statuses(report, label) == [WARN]

    def test_a_running_refresh_without_a_cache_says_so(self, project, monkeypatch):
        self.hold_refresh_lock(project)
        monkeypatch.setattr(preflight.dep_updates, "check", forbidden)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        assert "refresh in progress" in details(report, "dependency updates")

    def test_a_raising_check_is_a_warning_not_an_exception(self, project, monkeypatch):
        # preflight's contract is exit 0; a drift-check bug must not break it.
        def boom(*args, **kwargs):
            raise RuntimeError("bug")

        monkeypatch.setattr(preflight.dep_updates, "check", boom)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=False)
        assert statuses(report, "dependency updates") == [WARN]
        assert "RuntimeError" in details(report, "dependency updates")

    def test_offline_without_a_cache_says_so(self, project, monkeypatch):
        monkeypatch.setattr(preflight.dep_updates, "check", forbidden)
        report = preflight.Report()
        preflight.check_dependencies(report, project, offline=True)
        assert "no cached result" in details(report, "dependency updates (cached)")


class TestExtensions:
    def test_a_problem_warns_with_detail_lines(self, tmp_path, monkeypatch):
        ext = preflight.vscode_extensions
        found = ext.ExtReport(
            applicable=True,
            missing=["astral-sh.ty"],
            disabled_required=[],
            forbidden_active=[],
            ide=None,
            notes=[],
        )
        monkeypatch.setattr(ext, "check", lambda *a, **k: found)
        report = preflight.Report()
        preflight.check_extensions(report, tmp_path)
        assert statuses(report, "VS Code extensions") == [WARN]
        assert "missing (required): astral-sh.ty" in report.lines[0]

    def test_a_raising_check_is_a_warning_not_an_exception(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("bug")

        monkeypatch.setattr(preflight.vscode_extensions, "check", boom)
        report = preflight.Report()
        preflight.check_extensions(report, tmp_path)
        assert statuses(report, "VS Code extensions") == [WARN]
        assert "RuntimeError" in details(report, "VS Code extensions")

    def test_no_code_on_path_is_silent(self, tmp_path):
        report = preflight.Report()
        preflight.check_extensions(report, tmp_path)
        assert report.rows == []

    def test_an_absent_standard_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(preflight, "EXTENSION_STANDARD", tmp_path / "absent.toml")
        monkeypatch.setattr(preflight.vscode_extensions, "check", forbidden)
        report = preflight.Report()
        preflight.check_extensions(report, tmp_path)
        assert report.rows == []


class TestConfiguredRevs:
    """The regex silently matched only one of several common layouts, and
    the caller then reported success -- a false pass."""

    @pytest.mark.parametrize(
        ("style", "text"),
        [
            ("column_zero", "-   repo: https://github.com/a/b\n    rev: v1.0.0\n"),
            ("indented", "repos:\n  - repo: https://github.com/a/b\n    rev: v1.0.0\n"),
            (
                "comment_between",
                "-   repo: https://github.com/a/b\n    # why\n    rev: v1.0.0\n",
            ),
            ("quoted_rev", "-   repo: https://github.com/a/b\n    rev: 'v1.0.0'\n"),
        ],
    )
    def test_recognizes_common_layouts(self, tmp_path: Path, style: str, text: str):
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text(text)
        assert preflight.configured_revs(config) == [
            ("https://github.com/a/b", "v1.0.0")
        ], style

    def test_quoted_repo_url_is_not_dropped(self, tmp_path: Path):
        """Quotes were stripped from the rev but not the url, so a quoted url
        failed the http filter and vanished -- and a config where only some
        urls are quoted then reported "hook revs current" while a stale hook
        went unchecked. A false pass, which is the failure mode this whole
        check exists to avoid."""
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text(
            '-   repo: "https://github.com/a/b"\n    rev: v1.0.0\n'
            "-   repo: https://github.com/c/d\n    rev: v2.0.0\n"
        )
        assert preflight.configured_revs(config) == [
            ("https://github.com/a/b", "v1.0.0"),
            ("https://github.com/c/d", "v2.0.0"),
        ]

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            (
                "rev before repo",
                (
                    "-   rev: v1.0.0\n    repo: https://github.com/a/b\n"
                    "-   repo: https://github.com/c/d\n    rev: v2.0.0\n"
                ),
            ),
            (
                "keys between",
                (
                    "-   repo: https://github.com/a/b\n    hooks:\n"
                    "    -   id: x\n    rev: v1.0.0\n"
                    "-   repo: https://github.com/c/d\n    rev: v2.0.0\n"
                ),
            ),
        ],
    )
    def test_layouts_precommit_allows_are_not_dropped(
        self, tmp_path: Path, label: str, body: str
    ):
        """pre-commit accepts either key order and other keys between them. A
        reader requiring rev to follow repo dropped whole entries, and the
        survivors then reported "hook revs current" while a stale repo went
        unchecked."""
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text(body)
        pairs = preflight.configured_revs(config)
        assert [u for u, _ in pairs] == [
            "https://github.com/a/b",
            "https://github.com/c/d",
        ], label
        assert [r for _, r in pairs] == ["v1.0.0", "v2.0.0"], label

    def test_skips_non_http_repos(self, tmp_path: Path):
        """`repo: local` and `repo: meta` blocks have no upstream to query."""
        config = tmp_path / ".pre-commit-config.yaml"
        config.write_text("-   repo: local\n    rev: v1\n")
        assert preflight.configured_revs(config) == []


class TestHookRevs:
    def test_unparseable_config_warns_rather_than_passing(self, tmp_path: Path):
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n")
        report = preflight.Report()
        preflight.check_hook_revs(report, tmp_path)
        assert statuses(report, "hook revs current") == [WARN]
        assert "could not parse" in details(report, "hook revs current")

    def test_unreachable_remote_warns_rather_than_passing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A failed lookup used to be indistinguishable from up-to-date."""
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "-   repo: https://github.com/a/b\n    rev: v1.0.0\n"
        )
        monkeypatch.setattr(preflight, "latest_tag", lambda url: (None, "unreachable"))
        report = preflight.Report()
        preflight.check_hook_revs(report, tmp_path)
        assert statuses(report, "hook revs current") == [WARN]
        assert "lookup failed" in details(report, "hook revs current")

    def test_reachable_repo_with_no_tags_is_not_blamed_on_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """`git ls-remote --tags` on a tagless repo exits 0 with empty output,
        which is not a network failure."""
        monkeypatch.setattr(preflight, "git", lambda *a: "")
        assert preflight.latest_tag("https://example.invalid/x") == (
            None,
            "no-semver-tags",
        )

    def test_failed_command_is_still_unreachable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(preflight, "git", lambda *a: None)
        assert preflight.latest_tag("https://example.invalid/x") == (
            None,
            "unreachable",
        )

    def test_repo_without_semver_tags_is_not_blamed_on_the_network(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A repo tagged `v1.0` or with only pre-release tags used to report
        "lookup failed", pointing the reader at the network for a problem
        that needs the rev checked by hand."""
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "-   repo: https://github.com/a/b\n    rev: v1.0\n"
        )
        monkeypatch.setattr(
            preflight, "latest_tag", lambda url: (None, "no-semver-tags")
        )
        report = preflight.Report()
        preflight.check_hook_revs(report, tmp_path)
        assert statuses(report, "hook revs current") == [WARN]
        detail = details(report, "hook revs current")
        assert "check by hand" in detail and "lookup failed" not in detail

    def test_stale_rev_is_named(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "-   repo: https://github.com/a/b\n    rev: v1.0.0\n"
        )
        monkeypatch.setattr(preflight, "latest_tag", lambda url: ("v2.0.0", None))
        report = preflight.Report()
        preflight.check_hook_revs(report, tmp_path)
        assert statuses(report, "hook revs current") == [WARN]
        assert "v1.0.0 -> v2.0.0" in details(report, "hook revs current")

    def test_current_rev_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / ".pre-commit-config.yaml").write_text(
            "-   repo: https://github.com/a/b\n    rev: v1.0.0\n"
        )
        monkeypatch.setattr(preflight, "latest_tag", lambda url: ("v1.0.0", None))
        report = preflight.Report()
        preflight.check_hook_revs(report, tmp_path)
        assert statuses(report, "hook revs current") == [OK]


class TestHookInstalled:
    def test_detected_from_a_subdirectory(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """`--git-path` is relative to the process CWD, not the repo root.

        Joining it onto root escaped the repo entirely, so preflight
        reported the hook missing whenever it was run from anywhere but the
        top level.
        """
        (git_repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        hook = git_repo / ".git" / "hooks" / "pre-commit"
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text("#!/bin/sh\n# pre-commit\n")

        nested = git_repo / "deep" / "deeper"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        report = preflight.Report()
        preflight.check_precommit_installed(report, git_repo)
        assert statuses(report, "pre-commit hook installed") == [OK]

    def test_missing_hook_fails(self, git_repo: Path):
        (git_repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        report = preflight.Report()
        preflight.check_precommit_installed(report, git_repo)
        assert statuses(report, "pre-commit hook installed") == [FAIL]


class TestCodexHooks:
    def stub_registrar(
        self, monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str
    ) -> None:
        def fake_run(argv, **kwargs):
            assert argv == [
                sys.executable,
                str(REPO_ROOT / "scripts" / "register_codex_hooks.py"),
                "--check",
            ]
            return subprocess.CompletedProcess(argv, returncode, stdout, "")

        monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    def test_stale_configuration_warns_with_registrar_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Ignoring a nonzero check made a stale Codex adapter look current."""
        self.stub_registrar(monkeypatch, 1, "Codex hook registration is out of date.\n")
        report = preflight.Report()
        preflight.check_codex_hooks(report, tmp_path)
        assert statuses(report, "Codex hooks configured") == [WARN]
        assert "register_codex_hooks.py" in details(report, "Codex hooks configured")
        assert statuses(report, "Codex hooks trusted") == [WARN]
        assert "/hooks" in details(report, "Codex hooks trusted")

    def test_current_configuration_is_ok_but_trust_still_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        self.stub_registrar(monkeypatch, 0, "Codex hooks already registered.\n")
        report = preflight.Report()
        preflight.check_codex_hooks(report, tmp_path)
        assert statuses(report, "Codex hooks configured") == [OK]
        assert statuses(report, "Codex hooks trusted") == [WARN]
        assert "/hooks" in details(report, "Codex hooks trusted")


class TestTests:
    def test_absent_runner_reports_instead_of_raising(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A runner not on PATH used to raise FileNotFoundError out of the
        report entirely.

        Asserting that a bare command name (e.g. "task") is absent from PATH
        would be environment-dependent by construction -- this machine, for
        instance, has an unrelated `task` executable installed -- so the
        FileNotFoundError branch is exercised directly by stubbing
        subprocess.run rather than relying on real PATH contents.
        """
        (git_repo / "Taskfile.yml").write_text("tasks:\n  test:\n    cmds: [true]\n")

        def fake_run(*a, **kw):
            raise FileNotFoundError("task")

        monkeypatch.setattr(preflight.subprocess, "run", fake_run)
        report = preflight.Report()
        preflight.check_tests(report, git_repo, run=True)
        assert statuses(report, "tests") == [FAIL]
        assert "not found on PATH" in details(report, "tests")

    def test_no_suite_warns(self, git_repo: Path):
        report = preflight.Report()
        preflight.check_tests(report, git_repo, run=False)
        assert statuses(report, "tests") == [WARN]

    def test_detects_pixi_test_task_in_feature_table(self, git_repo: Path):
        """This repo defines `test` under [feature.dev.tasks], not [tasks],
        so a parser that only read the top-level table would miss it."""
        (git_repo / "pixi.toml").write_text('[feature.dev.tasks]\ntest = "pytest"\n')
        assert preflight.detect_test_command(git_repo) == "pixi run test"

    def test_pixi_without_test_task_is_not_detected(self, git_repo: Path):
        (git_repo / "pixi.toml").write_text('[tasks]\nlint = "ruff check ."\n')
        assert preflight.detect_test_command(git_repo) is None


class TestExitContract:
    def test_strict_is_nonzero_when_something_is_wrong(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.chdir(git_repo)
        isolate_preflight_home(monkeypatch, git_repo)
        assert preflight.main(["--strict"]) == 1

    def test_default_is_zero_even_with_warnings(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A SessionStart hook must never abort a session over a warning."""
        monkeypatch.chdir(git_repo)
        isolate_preflight_home(monkeypatch, git_repo)
        assert preflight.main([]) == 0


class TestFrictionRow:
    """The row is built from friction.py's JSON, so the parsing and the
    reporting are what these cover; the miner has its own tests."""

    def stub(self, monkeypatch: pytest.MonkeyPatch, payload: dict | str):
        text = payload if isinstance(payload, str) else json.dumps(payload)

        def fake_run(*a, **kw):
            return subprocess.CompletedProcess(a[0] if a else [], 0, text, "")

        monkeypatch.setattr(preflight.subprocess, "run", fake_run)

    def test_warns_when_classes_are_over_bar(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        self.stub(
            monkeypatch,
            {
                "actionable_count": 2,
                "actionable": ["write-before-read", "cmd-not-found"],
            },
        )
        report = preflight.Report()
        preflight.check_friction(report, git_repo)
        assert statuses(report, "friction") == [WARN]
        assert "write-before-read" in details(report, "friction")

    def test_ok_when_nothing_over_bar(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        self.stub(monkeypatch, {"actionable_count": 0, "actionable": []})
        report = preflight.Report()
        preflight.check_friction(report, git_repo)
        assert statuses(report, "friction") == [OK]

    def test_surfaces_ledger_warning_separately(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A suppression list that could not be read changes what the counts
        mean, so it cannot be folded into the count row."""
        self.stub(
            monkeypatch,
            {
                "actionable_count": 0,
                "actionable": [],
                "ledger_warning": "ledger unreadable",
            },
        )
        report = preflight.Report()
        preflight.check_friction(report, git_repo)
        assert statuses(report, "friction") == [WARN, OK]

    def test_unparseable_output_warns_rather_than_raising(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        self.stub(monkeypatch, "not json at all")
        report = preflight.Report()
        preflight.check_friction(report, git_repo)
        assert statuses(report, "friction") == [WARN]


class TestDeclaredFloor:
    def test_reads_pixi_toml(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text('[dependencies]\npython = ">=3.13"\n')
        assert preflight.declared_floor(tmp_path) == (3, 13)

    def test_reads_pyproject_requires_python(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text('requires-python = ">=3.12"\n')
        assert preflight.declared_floor(tmp_path) == (3, 12)

    def test_none_when_undeclared(self, tmp_path: Path):
        assert preflight.declared_floor(tmp_path) is None


class TestFloorParsing:
    def test_a_similarly_named_dependency_does_not_win(self, tmp_path: Path):
        """Unanchored, `python` matched the tail of `ipython = ">=8.0"`, which
        read as a floor of 8.0 -- and a failing interpreter check stops every
        later check, so one common dependency disabled the whole script."""
        (tmp_path / "pixi.toml").write_text(
            'ipython = ">=8.0"\njupyter = ">=7.0"\npython = ">=3.13"\n'
        )
        assert preflight.declared_floor(tmp_path) == (3, 13)


class TestInterpreter:
    """Every project carries its own environment with a current interpreter.
    Inheriting whatever `python3` the machine ships is how scripts end up
    contorted for a version nobody chose -- on macOS that is still 3.9.
    """

    def local_env(self, monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
        monkeypatch.setattr("sys.prefix", str(root / ".pixi" / "envs" / "dev"))

    def test_local_env_meeting_the_floor_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "pixi.toml").write_text('python = ">=3.0"\n')
        self.local_env(monkeypatch, tmp_path)
        report = preflight.Report()
        preflight.check_interpreter(report, tmp_path)
        assert statuses(report, "interpreter") == [OK]

    def test_inherited_interpreter_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "pixi.toml").write_text('python = ">=3.0"\n')
        monkeypatch.setattr("sys.prefix", "/usr/local")
        report = preflight.Report()
        preflight.check_interpreter(report, tmp_path)
        assert statuses(report, "interpreter") == [FAIL]
        assert "not a project-local env" in details(report, "interpreter")

    def test_below_the_declared_floor_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / "pixi.toml").write_text('python = ">=99.0"\n')
        self.local_env(monkeypatch, tmp_path)
        report = preflight.Report()
        preflight.check_interpreter(report, tmp_path)
        assert statuses(report, "interpreter") == [FAIL]
        assert "below the declared floor" in details(report, "interpreter")

    def test_undeclared_floor_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        self.local_env(monkeypatch, tmp_path)
        report = preflight.Report()
        preflight.check_interpreter(report, tmp_path)
        assert statuses(report, "interpreter") == [WARN]

    @pytest.mark.skipif(
        os.name == "nt",
        reason="os.symlink needs elevation or Developer Mode on Windows; the "
        "junction path is covered by tests/test_platform_paths.py",
    )
    def test_an_env_reached_through_a_symlink_is_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A git worktree commonly symlinks `.pixi` at the parent checkout's
        environment. Compared as written, that read as a foreign interpreter,
        which then discarded the entire step-0 gate in every worktree."""
        shared = tmp_path / "parent" / ".pixi"
        (shared / "envs" / "dev").mkdir(parents=True)
        root = tmp_path / "worktree"
        root.mkdir()
        (root / "pixi.toml").write_text('python = ">=3.0"\n')
        (root / ".pixi").symlink_to(shared)
        monkeypatch.setattr("sys.prefix", str(root / ".pixi" / "envs" / "dev"))
        report = preflight.Report()
        preflight.check_interpreter(report, root)
        assert statuses(report, "interpreter") == [OK]

    def test_a_project_with_no_pixi_manifest_only_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """These scripts are advertised as copyable into any project, and a
        conda named env or ~/.virtualenvs lives outside the checkout by
        design. Failing there reported one problem and inspected nothing."""
        monkeypatch.setattr("sys.prefix", "/opt/conda/envs/thesis")
        report = preflight.Report()
        preflight.check_interpreter(report, tmp_path)
        assert statuses(report, "interpreter") == [WARN]

    def test_a_non_local_interpreter_does_not_stop_the_other_checks(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """Locality says nothing about whether the remaining checks can run,
        and stopping on it printed two rows and skipped the branch, tree,
        pre-commit and test checks -- the whole gate."""
        monkeypatch.chdir(git_repo)
        monkeypatch.setattr("sys.prefix", "/usr/local")
        isolate_preflight_home(monkeypatch, git_repo)
        assert preflight.main([]) == 0
        assert "clean working tree" in capsys.readouterr().out

    def test_an_interpreter_below_the_floor_stops_the_other_checks(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """Too old is the case that genuinely makes later checks unrunnable:
        detect_test_command imports tomllib."""
        (git_repo / "pixi.toml").write_text('python = ">=99.0"\n')
        monkeypatch.chdir(git_repo)
        self.local_env(monkeypatch, git_repo)
        isolate_preflight_home(monkeypatch, git_repo)
        assert preflight.main(["--strict"]) == 1
        assert "clean working tree" not in capsys.readouterr().out


class TestAuditOwed:
    """The marker is gitignored branch state, so nothing else can report it."""

    def report_for(self, root):
        report = preflight.Report()
        preflight.check_audit_owed(report, root)
        return report.rows

    def test_marker_with_assets_is_reported(self, tmp_path):
        (tmp_path / ".audit-owed").write_text("scripts/x.py\nAGENTS.md\n")
        rows = self.report_for(tmp_path)
        assert len(rows) == 1
        status, label, detail = rows[0]
        assert status == preflight.WARN and label == "audit"
        assert "2 config asset(s)" in detail and "pixi run audit" in detail

    def test_absent_marker_is_silent(self, tmp_path):
        assert self.report_for(tmp_path) == []

    def test_empty_marker_is_silent(self, tmp_path):
        """A hook that wrote nothing should not produce a standing warning."""
        (tmp_path / ".audit-owed").write_text("\n\n")
        assert self.report_for(tmp_path) == []

    def test_a_directory_named_like_the_marker_is_silent(self, tmp_path):
        (tmp_path / ".audit-owed").mkdir()
        assert self.report_for(tmp_path) == []


class TestAuditOwedBranchScoping:
    """Each line is `<branch>\tasset`. Unscoped, the warning follows you to an
    unrelated branch, and clearing it there discards the original obligation.

    Driven through a real throwaway repo rather than a bare tmp_path: reading
    the branch from the process cwd made these tests depend on whichever branch
    the checkout was on, and two of them failed on `main` -- the state step 0
    requires to be green.
    """

    def report_for(self, root):
        report = preflight.Report()
        preflight.check_audit_owed(report, root)
        return report.rows

    def on_branch(self, repo, name):
        run_git(repo, "checkout", "-q", "-b", name)
        return repo

    def test_this_branch_s_entries_are_counted(self, git_repo):
        self.on_branch(git_repo, "feat/x")
        (git_repo / ".audit-owed").write_text(
            "feat/x\tscripts/x.py\nfeat/x\tAGENTS.md\n"
        )
        assert "2 config asset(s)" in self.report_for(git_repo)[0][2]

    def test_another_branch_s_entries_are_ignored(self, git_repo):
        self.on_branch(git_repo, "feat/x")
        (git_repo / ".audit-owed").write_text("feat/other\tscripts/x.py\n")
        assert self.report_for(git_repo) == []

    def test_a_mixed_marker_counts_only_this_branch(self, git_repo):
        self.on_branch(git_repo, "feat/x")
        (git_repo / ".audit-owed").write_text(
            "feat/other\tscripts/a.py\nfeat/x\tscripts/b.py\n"
        )
        assert "1 config asset(s)" in self.report_for(git_repo)[0][2]

    def test_the_default_branch_sees_every_branch_s_entries(self, git_repo):
        """Merged work is now the default branch's contents, so an obligation
        recorded against a feature branch is no longer someone else's."""
        (git_repo / ".audit-owed").write_text(
            "feat/a\tscripts/a.py\nfeat/b\tscripts/b.py\n"
        )
        assert "2 config asset(s)" in self.report_for(git_repo)[0][2]

    def test_an_unscoped_line_still_counts(self, git_repo):
        """Written before scoping existed; the safe reading of an obligation
        with no recorded owner is that it is still owed."""
        self.on_branch(git_repo, "feat/x")
        (git_repo / ".audit-owed").write_text("scripts/legacy.py\n")
        assert "1 config asset(s)" in self.report_for(git_repo)[0][2]


class TestSkillsLinked:
    """Skills reach a session only through symlinks that install.sh writes,
    so an added skill is invisible until it is re-run -- machine state, like
    hook registration, which is why it is reported rather than tested. Adding
    a skill and forgetting the install left `pixi run all` green and the
    skill absent from every session.
    """

    def project(self, root: Path, *names: str) -> Path:
        # Gated on install.py, not install.sh: the installer is
        # platform-dispatched (install.ps1 on Windows), and install.py is the
        # one file present under every dispatch.
        (root / "install.py").write_text("", encoding="utf-8")
        for name in names:
            (root / "skills" / name).mkdir(parents=True)
        installed = root / "installed"
        installed.mkdir()
        return installed

    def link(self, installed: Path, name: str, target: Path) -> None:
        platform_paths.link_dir(target, installed / name)

    def test_ok_when_every_skill_is_linked(self, tmp_path: Path):
        installed = self.project(tmp_path, "alpha", "beta")
        for name in ("alpha", "beta"):
            self.link(installed, name, tmp_path / "skills" / name)
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [OK]

    def test_warns_about_a_skill_that_was_never_linked(self, tmp_path: Path):
        installed = self.project(tmp_path, "alpha", "beta")
        self.link(installed, "alpha", tmp_path / "skills" / "alpha")
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [WARN]
        assert "beta" in details(report, "skills linked")

    def test_warns_about_a_link_whose_skill_is_gone(self, tmp_path: Path):
        installed = self.project(tmp_path, "alpha")
        self.link(installed, "alpha", tmp_path / "skills" / "alpha")
        # link_dir requires a real target, unlike the dangling link this
        # simulates, so the junction/symlink is built by hand here.
        gone = tmp_path / "skills" / "renamed-away"
        gone.mkdir()
        self.link(installed, "renamed-away", gone)
        gone.rmdir()
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [WARN]
        assert "renamed-away" in details(report, "skills linked")

    def test_silent_in_a_project_that_installs_no_skills(self, tmp_path: Path):
        """preflight is copied into projects verbatim, and a `skills/`
        directory with no installer says nothing about this machine."""
        (tmp_path / "skills").mkdir()
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, tmp_path / "installed")
        assert report.rows == []

    def test_a_worktree_link_into_the_parent_checkout_is_not_a_copy(
        self, git_repo: Path
    ):
        installed = self.project(git_repo, "alpha")
        (git_repo / "skills" / "alpha" / "SKILL.md").write_text("alpha\n")
        run_git(git_repo, "add", "install.py", "skills")
        run_git(git_repo, "commit", "-qm", "skill sources")
        worktree = git_repo / "linked worktree"
        run_git(git_repo, "worktree", "add", "-q", "-b", "feature", str(worktree))
        self.link(installed, "alpha", git_repo / "skills" / "alpha")
        report = preflight.Report()
        preflight.check_skills(report, worktree, installed)
        assert statuses(report, "skills linked") == [OK]

    @pytest.mark.parametrize("target", ["other/skills/alpha", "skills/beta"])
    def test_a_live_link_to_the_wrong_skill_source_warns(self, tmp_path, target):
        installed = self.project(tmp_path, "alpha")
        wrong_source = tmp_path / target
        wrong_source.mkdir(parents=True)
        if target.startswith("other/"):
            run_git(tmp_path / "other", "init", "-q", "-b", "main", ".")
        else:
            self.link(installed, "beta", wrong_source)
        self.link(installed, "alpha", wrong_source)
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [WARN]
        assert "wrong target: alpha" in details(report, "skills linked")

    def test_a_copy_is_reported_rather_than_counted_as_linked(self, tmp_path: Path):
        # The failure mode this check exists for: Git Bash's `ln -s` deep-copies
        # instead of failing on a Windows machine without Developer Mode, so a
        # copy looks installed and silently stops tracking the repo.
        installed = self.project(tmp_path, "alpha")
        shutil.copytree(tmp_path / "skills" / "alpha", installed / "alpha")
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [WARN]
        assert "alpha" in details(report, "skills linked")
        assert "copy" in details(report, "skills linked")
        assert str(installed) in details(report, "skills linked")


def make_installable_project(root: Path) -> Path:
    """Build the minimum repository shape that owns installation checks."""
    (root / "install.py").write_text("", encoding="utf-8")
    (root / "AGENTS.md").write_text("canonical guidance\n", encoding="utf-8")
    return root


def write_expected_adapters(root: Path, home: Path) -> None:
    for dest, expected in preflight.installation_contract.instruction_adapters(
        root, home
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(expected, encoding="utf-8")


class TestInstructionAdapters:
    def test_current_instruction_adapters_are_ok(self, tmp_path: Path):
        root = make_installable_project(tmp_path)
        home = tmp_path / "home"
        write_expected_adapters(root, home)
        report = preflight.Report()
        preflight.check_instructions(report, root, home)
        assert statuses(report, "Claude instructions") == [OK]
        assert statuses(report, "Codex instructions") == [OK]
        assert str(home / ".claude" / "CLAUDE.md") in details(
            report, "Claude instructions"
        )
        assert str(home / ".codex" / "AGENTS.md") in details(
            report, "Codex instructions"
        )

    def test_a_missing_claude_adapter_warns_with_its_path(self, tmp_path: Path):
        root = make_installable_project(tmp_path)
        home = tmp_path / "home"
        write_expected_adapters(root, home)
        (home / ".claude" / "CLAUDE.md").unlink()
        report = preflight.Report()
        preflight.check_instructions(report, root, home)
        assert statuses(report, "Claude instructions") == [WARN]
        assert str(home / ".claude" / "CLAUDE.md") in details(
            report, "Claude instructions"
        )

    def test_a_stale_codex_snapshot_warns(self, tmp_path: Path):
        root = make_installable_project(tmp_path)
        home = tmp_path / "home"
        write_expected_adapters(root, home)
        (home / ".codex" / "AGENTS.md").write_text("stale", encoding="utf-8")
        report = preflight.Report()
        preflight.check_instructions(report, root, home)
        assert statuses(report, "Codex instructions") == [WARN]
        assert "install" in details(report, "Codex instructions")
        assert str(home / ".codex" / "AGENTS.md") in details(
            report, "Codex instructions"
        )

    def test_a_linked_adapter_warns_with_its_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        root = make_installable_project(tmp_path)
        home = tmp_path / "home"
        write_expected_adapters(root, home)
        claude_adapter = home / ".claude" / "CLAUDE.md"
        real_is_link = preflight.platform_paths.is_link
        monkeypatch.setattr(
            preflight.platform_paths,
            "is_link",
            lambda path: Path(path) == claude_adapter or real_is_link(path),
        )
        report = preflight.Report()
        preflight.check_instructions(report, root, home)
        assert statuses(report, "Claude instructions") == [WARN]
        assert str(claude_adapter) in details(report, "Claude instructions")


class TestSkillDestinationOrchestration:
    def test_main_checks_both_skill_destinations(
        self,
        git_repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        root = make_installable_project(git_repo)
        (root / "skills" / "alpha").mkdir(parents=True)
        home = tmp_path / "home"
        write_expected_adapters(root, home)
        claude_skills = home / ".claude" / "skills"
        claude_skills.mkdir(parents=True)
        platform_paths.link_dir(root / "skills" / "alpha", claude_skills / "alpha")
        monkeypatch.chdir(git_repo)
        assert isolate_preflight_home(monkeypatch, tmp_path) == home
        assert preflight.main(["--no-friction"]) == 0
        output = capsys.readouterr().out
        assert "Claude skills linked" in output
        assert str(claude_skills) in output
        assert "Portable skills linked" in output
        assert str(home / ".agents" / "skills") in output


class TestCopiedAloneIntoANewProject:
    """The docstring and README both advertise this file as copyable into a
    new project verbatim, and `scripts/platform_paths.py` is deliberately not
    on that list -- it is described as a library module, not a copied tool.

    So a bare copy has to work. It did not: the sibling was loaded
    unconditionally at module scope, so a copy raised FileNotFoundError from
    the import before a single check ran -- and in a script whose exit
    contract is 0 unless --strict, precisely so a SessionStart hook can never
    abort a session over a warning.
    """

    def copy_alone(self, tmp_path: Path) -> Path:
        target = tmp_path / "preflight.py"
        shutil.copy(REPO_ROOT / "scripts" / "preflight.py", target)
        subprocess.run(
            ["git", "init", "-q", "-b", "main", "."], cwd=tmp_path, check=True
        )
        return target

    def copy_with_contract(self, tmp_path: Path) -> Path:
        script = self.copy_alone(tmp_path)
        shutil.copy(
            REPO_ROOT / "scripts" / "installation_contract.py",
            tmp_path / "installation_contract.py",
        )
        return script

    def load_script(self, script: Path):
        spec = importlib.util.spec_from_file_location("copied_preflight", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_a_bare_copy_still_reports_rather_than_crashing(self, tmp_path: Path):
        script = self.copy_alone(tmp_path)
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            # The point of the test is that it exits 0; asserting that is
            # more informative than raising on it.
            check=False,
        )
        assert "Traceback" not in result.stderr, result.stderr
        assert "FileNotFoundError" not in result.stderr
        assert result.returncode == 0
        # It ran the checks that do not need the sibling.
        assert "git repository" in result.stdout

    def test_the_checks_that_need_the_sibling_skip_silently(self, tmp_path: Path):
        """The idiom this file already uses for every other optional sibling:
        skip, rather than warn about a file the reader did not copy on
        purpose."""
        script = self.copy_alone(tmp_path)
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            # The point of the test is that it exits 0; asserting that is
            # more informative than raising on it.
            check=False,
        )
        assert "skills linked" not in result.stdout
        assert "instructions" not in result.stdout

    def test_instruction_checks_skip_without_platform_paths(self, tmp_path: Path):
        script = self.copy_with_contract(tmp_path)
        module = self.load_script(script)
        (tmp_path / "install.py").write_text("", encoding="utf-8")
        (tmp_path / "AGENTS.md").write_text("canonical guidance\n", encoding="utf-8")
        home = tmp_path / "home"
        for dest, expected in module.installation_contract.instruction_adapters(
            tmp_path, home
        ):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(expected, encoding="utf-8")
        report = module.Report()
        module.check_instructions(report, tmp_path, home)
        assert report.rows == []


class TestInstallHintWithoutTheSibling:
    """The fallback branch added when platform_paths became optional. It is
    one boolean, but it is the boolean that decides whether a Windows user is
    told to run install.sh -- the wrong command entirely, not a cosmetic
    mismatch."""

    def test_the_sibling_decides_when_it_is_present(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        class Stub:
            WINDOWS = True

        monkeypatch.setattr(preflight, "platform_paths", Stub)
        assert preflight._install_hint() == "./install.ps1"

    def test_os_name_decides_when_it_is_absent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(preflight, "platform_paths", None)
        monkeypatch.setattr(preflight.os, "name", "nt")
        assert preflight._install_hint() == "./install.ps1"
        monkeypatch.setattr(preflight.os, "name", "posix")
        assert preflight._install_hint() == "./install.sh"
