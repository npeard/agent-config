"""Regression tests for scripts/preflight.py.

Every case here corresponds to a bug that actually shipped and was caught
in review, rather than to a restatement of the implementation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import preflight
import pytest

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
    def test_absent_runner_reports_instead_of_raising(self, git_repo: Path):
        """A runner not on PATH used to raise FileNotFoundError out of the
        report entirely."""
        (git_repo / "Taskfile.yml").write_text("tasks:\n  test:\n    cmds: [true]\n")
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

    def test_a_failing_interpreter_stops_the_other_checks(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A wrong interpreter makes later results untrustworthy and some of
        them unrunnable, so preflight reports and stops rather than guessing.
        """
        monkeypatch.chdir(git_repo)
        monkeypatch.setattr("sys.prefix", "/usr/local")
        assert preflight.main(["--strict"]) == 1


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
