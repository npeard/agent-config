"""Regression tests for scripts/preflight.py.

Every case here corresponds to a bug that actually shipped and was caught
in review, rather than to a restatement of the implementation.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import platform_paths
import preflight
import pytest
from conftest import run_git

OK, WARN, FAIL = preflight.OK, preflight.WARN, preflight.FAIL


def statuses(report: preflight.Report, label: str) -> list[str]:
    return [s for s, lab, _ in report.rows if lab == label]


def details(report: preflight.Report, label: str) -> str:
    return " ".join(d for _, lab, d in report.rows if lab == label)


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
        assert preflight.main(["--strict"]) == 1

    def test_default_is_zero_even_with_warnings(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A SessionStart hook must never abort a session over a warning."""
        monkeypatch.chdir(git_repo)
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
        assert preflight.main(["--strict"]) == 1
        assert "clean working tree" not in capsys.readouterr().out


class TestAuditOwed:
    """The marker is gitignored branch state, so nothing else can report it."""

    def report_for(self, root):
        report = preflight.Report()
        preflight.check_audit_owed(report, root)
        return report.rows

    def test_marker_with_assets_is_reported(self, tmp_path):
        (tmp_path / ".audit-owed").write_text("scripts/x.py\nCLAUDE.md\n")
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
            "feat/x\tscripts/x.py\nfeat/x\tCLAUDE.md\n"
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
        self, tmp_path: Path
    ):
        """The case this check's docstring says it matches by name to avoid.

        main() passes `root` as `git rev-parse --show-toplevel`, which inside
        a worktree is the worktree -- while the installed links still point at
        the parent checkout they were written from. Comparing targets against
        `root` reported every skill as "copy, not a link" and told the user to
        re-run the installer, which would relink them away from the parent.
        This repo's CLAUDE.md mandates worktrees for parallel phases.
        """
        parent = tmp_path / "parent"
        (parent / "skills" / "alpha").mkdir(parents=True)
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        installed = self.project(worktree, "alpha")
        # Linked from the parent checkout, as a real install would have been.
        self.link(installed, "alpha", parent / "skills" / "alpha")
        report = preflight.Report()
        preflight.check_skills(report, worktree, installed)
        assert statuses(report, "skills linked") == [OK]

    def test_a_copy_is_reported_rather_than_counted_as_linked(self, tmp_path: Path):
        # The failure mode this check exists for: Git Bash's `ln -s` deep-copies
        # instead of failing on a Windows machine without Developer Mode, so a
        # copy looks installed and silently stops tracking the repo.
        import shutil

        installed = self.project(tmp_path, "alpha")
        shutil.copytree(tmp_path / "skills" / "alpha", installed / "alpha")
        report = preflight.Report()
        preflight.check_skills(report, tmp_path, installed)
        assert statuses(report, "skills linked") == [WARN]
        assert "alpha" in details(report, "skills linked")
        assert "copy" in details(report, "skills linked")
