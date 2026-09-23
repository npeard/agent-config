"""Tests for scripts/vscode_extensions.py.

Every external effect (`code --list-extensions`, the global disabled list,
the IDE lock, the environment, pid liveness) is injected, so nothing here
touches the real VS Code state db, spawns a real `code`, or reads a real
IDE lock -- see the Global Constraints in the environment-drift-checks
plan. sqlite fixtures are real files under tmp_path, not fakes, because
read_disabled_from's contract is specifically about how sqlite behaves
when locked or malformed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import vscode_extensions

REPO = Path(__file__).resolve().parent.parent


def make_standard(required=(), forbidden=()) -> vscode_extensions.Standard:
    return vscode_extensions.Standard(
        required=dict(required),
        forbidden=dict(forbidden),
    )


def fake_run(stdout_lines):
    """A `run` fake that reports `code --list-extensions` as this stdout."""

    def _run(argv):
        assert argv[0] == "code"
        return subprocess.CompletedProcess(
            argv, returncode=0, stdout="\n".join(stdout_lines), stderr=""
        )

    return _run


def code_missing(argv):
    return None


def known_disabled(ids):
    return lambda: set(ids)


def unknown_disabled():
    return lambda: None


NO_IDE_ENV: dict[str, str] = {}


def no_ide_alive(pid):
    raise AssertionError("pid_alive should not be consulted when there is no IDE check")


def check_defaults(**overrides):
    """check() with every dependency defaulted to an inert fake, so a test
    overriding one argument does not have to restate the rest."""
    kwargs = {
        "root": Path("/project"),
        "run": fake_run([]),
        "read_disabled": known_disabled([]),
        "ide_dir": Path("/nonexistent-ide-dir"),
        "env": NO_IDE_ENV,
        "pid_alive": no_ide_alive,
    }
    kwargs.update(overrides)
    return kwargs


class TestLoadStandard:
    def test_lowercases_ids_and_keeps_reasons(self, tmp_path):
        toml = tmp_path / "standard.toml"
        toml.write_text(
            """
            [required."Some.Extension"]
            reason = "why"

            [forbidden."Other.Thing"]
            reason = "why not"
            """,
            encoding="utf-8",
        )
        standard = vscode_extensions.load_standard(toml)
        assert standard.required == {"some.extension": "why"}
        assert standard.forbidden == {"other.thing": "why not"}

    def test_the_shipped_standard_loads(self):
        standard = vscode_extensions.load_standard(REPO / "vscode-extensions.toml")
        assert "ms-python.vscode-pylance" in standard.forbidden
        assert "anthropic.claude-code" in standard.required
        assert all(standard.required.values())
        assert all(standard.forbidden.values())


class TestCheckExtensions:
    def test_missing_required(self):
        standard = make_standard(required={"a.one": "r1", "a.two": "r2"})
        report = vscode_extensions.check(
            standard, **check_defaults(run=fake_run(["a.one"]))
        )
        assert report.missing == ["a.two"]

    def test_disabled_required_is_reported(self):
        standard = make_standard(required={"a.one": "r1"})
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run(["a.one"]), read_disabled=known_disabled(["a.one"])
            ),
        )
        assert report.missing == []
        assert report.disabled_required == ["a.one"]

    def test_forbidden_installed_and_enabled_is_reported(self):
        standard = make_standard(forbidden={"bad.ext": "reason"})
        report = vscode_extensions.check(
            standard, **check_defaults(run=fake_run(["bad.ext"]))
        )
        assert report.forbidden_active == [("bad.ext", "reason")]

    def test_forbidden_installed_but_disabled_is_not_reported(self):
        standard = make_standard(forbidden={"bad.ext": "reason"})
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run(["bad.ext"]), read_disabled=known_disabled(["bad.ext"])
            ),
        )
        assert report.forbidden_active == []

    def test_unlisted_extension_is_never_reported(self):
        standard = make_standard(required={"a.one": "r1"})
        report = vscode_extensions.check(
            standard, **check_defaults(run=fake_run(["a.one", "some.unrelated-ext"]))
        )
        assert report.missing == []
        assert report.disabled_required == []
        assert report.forbidden_active == []

    def test_ids_from_code_are_matched_case_insensitively(self):
        standard = make_standard(required={"a.one": "r1"})
        report = vscode_extensions.check(
            standard, **check_defaults(run=fake_run(["A.ONE"]))
        )
        assert report.missing == []

    def test_code_absent_skips_the_whole_check(self):
        standard = make_standard(required={"a.one": "r1"})
        report = vscode_extensions.check(standard, **check_defaults(run=code_missing))
        assert report.applicable is False
        assert report.missing == []
        assert report.disabled_required == []
        assert report.forbidden_active == []

    def test_enabled_state_unknown_still_reports_missing(self):
        """Review Focus 3: a locked or missing state db. Missing required
        extensions do not depend on the disabled list at all, so they are
        still reported even when enabled state is unknown."""
        standard = make_standard(required={"a.one": "r1"})
        report = vscode_extensions.check(
            standard,
            **check_defaults(run=fake_run([]), read_disabled=unknown_disabled()),
        )
        assert report.missing == ["a.one"]

    def test_enabled_state_unknown_reports_forbidden_as_installed(self):
        """Review Focus 3: disabling a forbidden extension normally clears
        it, but when the disabled list cannot be read, an installed
        forbidden extension is reported regardless -- the safer read."""
        standard = make_standard(forbidden={"bad.ext": "reason"})
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run(["bad.ext"]), read_disabled=unknown_disabled()
            ),
        )
        assert report.forbidden_active == [("bad.ext", "reason")]
        assert any("unknown" in note for note in report.notes)


class TestIdeCheck:
    def make_lock(
        self, tmp_path, port, *, pid, workspace_folders, token="secret-token"
    ):
        ide_dir = tmp_path / "ide"
        ide_dir.mkdir()
        (ide_dir / f"{port}.lock").write_text(
            json.dumps(
                {
                    "pid": pid,
                    "workspaceFolders": workspace_folders,
                    "authToken": token,
                }
            ),
            encoding="utf-8",
        )
        return ide_dir

    def test_not_in_a_vscode_terminal_skips_the_check(self, tmp_path):
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                env={},
                ide_dir=tmp_path / "ide",
                pid_alive=no_ide_alive,
            ),
        )
        assert report.ide is None

    def test_live_pid_and_matching_workspace_is_fine(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        ide_dir = self.make_lock(
            tmp_path, 28330, pid=4242, workspace_folders=[str(root)]
        )
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                root=root,
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "28330"},
                ide_dir=ide_dir,
                pid_alive=lambda pid: pid == 4242,
            ),
        )
        assert report.ide is None

    def test_dead_pid_is_a_problem(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        ide_dir = self.make_lock(
            tmp_path, 28330, pid=4242, workspace_folders=[str(root)]
        )
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                root=root,
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "28330"},
                ide_dir=ide_dir,
                pid_alive=lambda pid: False,
            ),
        )
        assert report.ide is not None
        assert "not connected" in report.ide

    def test_wrong_workspace_is_a_problem(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        other = tmp_path / "other-project"
        other.mkdir()
        ide_dir = self.make_lock(
            tmp_path, 28330, pid=4242, workspace_folders=[str(other)]
        )
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                root=root,
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "28330"},
                ide_dir=ide_dir,
                pid_alive=lambda pid: True,
            ),
        )
        assert report.ide is not None

    def test_windows_lowercased_drive_and_case_still_matches(self, tmp_path):
        """Review Focus 5: a project path containing spaces, matched against
        the lock's workspaceFolders, which Windows lowercases (e.g.
        'c:\\\\Users\\\\...'). Compared as normalized, case-folded resolved
        paths, not verbatim strings."""
        root = tmp_path / "My Project" / "has spaces"
        root.mkdir(parents=True)
        # Simulate what Windows actually writes: a lowercased drive letter
        # and a differently-cased tail, as the plan's captured fact states.
        raw = str(root.resolve())
        if len(raw) > 1 and raw[1] == ":":
            mangled = raw[0].lower() + raw[1:]
        else:
            mangled = raw.upper()
        ide_dir = self.make_lock(tmp_path, 28330, pid=4242, workspace_folders=[mangled])
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                root=root,
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "28330"},
                ide_dir=ide_dir,
                pid_alive=lambda pid: True,
            ),
        )
        assert report.ide is None

    def test_missing_port_env_var_is_a_problem(self, tmp_path):
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                env={"TERM_PROGRAM": "vscode"},
                ide_dir=tmp_path / "ide",
                pid_alive=no_ide_alive,
            ),
        )
        assert report.ide is not None

    def test_missing_lock_file_is_a_problem(self, tmp_path):
        standard = make_standard()
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run([]),
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "9999"},
                ide_dir=tmp_path / "ide",
                pid_alive=no_ide_alive,
            ),
        )
        assert report.ide is not None

    def test_auth_token_never_appears_anywhere_in_the_report(self, tmp_path):
        root = tmp_path / "project"
        root.mkdir()
        ide_dir = self.make_lock(
            tmp_path,
            28330,
            pid=4242,
            workspace_folders=[str(root)],
            token="do-not-leak-me",
        )
        standard = make_standard(
            required={"a.one": "r1"}, forbidden={"bad.ext": "reason"}
        )
        report = vscode_extensions.check(
            standard,
            **check_defaults(
                run=fake_run(["bad.ext"]),
                root=root,
                env={"TERM_PROGRAM": "vscode", "CLAUDE_CODE_SSE_PORT": "28330"},
                ide_dir=ide_dir,
                pid_alive=lambda pid: False,  # force a problem, the likelier leak site
            ),
        )
        blob = repr(report)
        summary, lines = vscode_extensions.render(report)
        blob += summary + "\n".join(lines)
        assert "do-not-leak-me" not in blob


class TestRender:
    def test_not_applicable(self):
        report = vscode_extensions.ExtReport(
            applicable=False,
            missing=[],
            disabled_required=[],
            forbidden_active=[],
            ide=None,
            notes=[],
        )
        summary, lines = vscode_extensions.render(report)
        assert "not applicable" in summary
        assert lines == []

    def test_a_clean_report_says_ok(self):
        report = vscode_extensions.ExtReport(
            applicable=True,
            missing=[],
            disabled_required=[],
            forbidden_active=[],
            ide=None,
            notes=[],
        )
        summary, _lines = vscode_extensions.render(report)
        assert "ok" in summary

    def test_problems_are_counted_and_detailed(self):
        report = vscode_extensions.ExtReport(
            applicable=True,
            missing=["a.one"],
            disabled_required=[],
            forbidden_active=[("bad.ext", "reason text")],
            ide=None,
            notes=[],
        )
        summary, lines = vscode_extensions.render(report)
        assert "2" in summary
        joined = "\n".join(lines)
        assert "a.one" in joined
        assert "bad.ext" in joined
        assert "reason text" in joined


class TestReadDisabledFrom:
    def make_db(self, tmp_path, value=None):
        db = tmp_path / "state.vscdb"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
        if value is not None:
            conn.execute(
                "INSERT INTO ItemTable VALUES (?, ?)",
                ("extensionsIdentifiers/disabled", value),
            )
        conn.commit()
        conn.close()
        return db

    def test_missing_db_is_unknown(self, tmp_path):
        assert vscode_extensions.read_disabled_from(tmp_path / "nope.vscdb") is None

    def test_reads_and_lowercases_ids(self, tmp_path):
        db = self.make_db(
            tmp_path, json.dumps([{"id": "Github.Copilot-Chat"}, {"id": "a.b"}])
        )
        assert vscode_extensions.read_disabled_from(db) == {
            "github.copilot-chat",
            "a.b",
        }

    def test_no_key_present_means_known_and_empty(self, tmp_path):
        db = self.make_db(tmp_path, value=None)
        assert vscode_extensions.read_disabled_from(db) == set()

    def test_malformed_json_is_unknown(self, tmp_path):
        db = self.make_db(tmp_path, "{not json")
        assert vscode_extensions.read_disabled_from(db) is None

    def test_locked_db_is_unknown(self, tmp_path):
        """Review Focus 3: VS Code holding the db open must not raise out of
        this function -- it degrades to 'unknown' instead."""
        db = self.make_db(tmp_path, json.dumps([{"id": "a.b"}]))
        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("INSERT INTO ItemTable VALUES ('x', 'y')")
        try:
            assert vscode_extensions.read_disabled_from(db) is None
        finally:
            holder.close()

    def test_opened_read_only_never_writes(self, tmp_path):
        db = self.make_db(tmp_path, json.dumps([{"id": "a.b"}]))
        before = db.stat().st_mtime_ns
        vscode_extensions.read_disabled_from(db)
        assert db.stat().st_mtime_ns == before


class TestRunCode:
    """_run_code's own contract: resolve `code` through PATH like a shell
    would, not like a bare CreateProcess call.

    On Windows, VS Code installs `code` as `code.cmd`; subprocess.run does
    not consult PATHEXT the way a shell does, so handing it the bare name
    raised FileNotFoundError for a `code` that genuinely was on PATH -- the
    exact bug this locks in against a regression.
    """

    def _make_fake_code(self, tmp_path):
        if os.name == "nt":
            script = tmp_path / "code.cmd"
            script.write_text("@echo fake.extension.one\r\n", encoding="utf-8")
        else:
            script = tmp_path / "code"
            script.write_text("#!/bin/sh\necho fake.extension.one\n", encoding="utf-8")
            script.chmod(0o755)
        return script

    def test_resolves_a_path_shim_and_runs_it(self, tmp_path, monkeypatch):
        self._make_fake_code(tmp_path)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
        result = vscode_extensions._run_code(["code", "--list-extensions"])
        assert result is not None
        assert "fake.extension.one" in result.stdout

    def test_none_when_not_on_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PATH", str(tmp_path))
        assert vscode_extensions._run_code(["definitely-not-a-real-command"]) is None


class TestMain:
    def test_reports_zero_when_clean(self, tmp_path, monkeypatch, capsys):
        toml = tmp_path / "standard.toml"
        toml.write_text('[required."a.one"]\nreason = "r"\n', encoding="utf-8")
        monkeypatch.setattr(
            vscode_extensions,
            "_run_code",
            fake_run(["a.one"]),
        )
        monkeypatch.setattr(vscode_extensions, "read_disabled_from", lambda _db: set())
        # Not the real environment's own IDE state -- this session runs
        # inside a VS Code terminal, and main() reads os.environ for real.
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SSE_PORT", raising=False)
        rc = vscode_extensions.main([str(toml), "--root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ok" in out

    def test_missing_toml_is_an_error_not_a_crash(self, tmp_path):
        rc = vscode_extensions.main([str(tmp_path / "nope.toml")])
        assert rc == 1
