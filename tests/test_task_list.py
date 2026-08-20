"""Contract tests for hooks/task-list.py.

Exercised as a subprocess through its real contract -- JSON in, optional
JSON out -- like the other hook. It runs under `sys.executable`, so this
covers the contract rather than any claim about interpreter portability; the
hook's own reason for avoiding tomllib is stated in its docstring.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "task-list.py"


def run(cwd: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        check=True,
    )
    out = result.stdout.strip()
    if not out:
        return ""
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return payload["hookSpecificOutput"]["additionalContext"]


class TestSilence:
    def test_no_manifest_emits_nothing(self, tmp_path: Path):
        """A project with no runner should pay nothing, and an empty section
        only teaches the reader to skip this block."""
        assert run(tmp_path) == ""

    def test_manifest_with_no_tasks_emits_nothing(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text("[dependencies]\npython = '*'\n")
        assert run(tmp_path) == ""

    def test_malformed_payload_does_not_crash(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json",
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.returncode == 0


class TestDiscovery:
    def test_pixi_default_and_feature_tables(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text(
            '[tasks]\nascii = "python x.py"\n[feature.dev.tasks]\ntest = "pytest -q"\n'
        )
        out = run(tmp_path)
        assert "pixi run <name>" in out
        assert "ascii" in out and "test" in out and "pytest -q" in out

    def test_pixi_dependencies_are_not_mistaken_for_tasks(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text(
            '[dependencies]\nruff = "*"\n[tasks]\nlint = "ruff check ."\n'
        )
        out = run(tmp_path)
        assert "lint" in out
        assert "\n  ruff" not in out

    def test_package_json_scripts(self, tmp_path: Path):
        (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}')
        out = run(tmp_path)
        assert "npm run <name>" in out and "build" in out

    def test_taskfile(self, tmp_path: Path):
        (tmp_path / "Taskfile.yml").write_text(
            "version: '3'\ntasks:\n  build:\n    cmds: [echo hi]\n"
        )
        out = run(tmp_path)
        assert "task <name>" in out and "build" in out

    def test_makefile(self, tmp_path: Path):
        (tmp_path / "Makefile").write_text(".PHONY: all\nall:\n\techo hi\n")
        out = run(tmp_path)
        assert "make <name>" in out and "all" in out

    def test_reports_every_manifest_present(self, tmp_path: Path):
        """A repo may legitimately have two runners; reporting only the first
        would hide half the commands."""
        (tmp_path / "pixi.toml").write_text('[tasks]\nfmt = "ruff format ."\n')
        (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}')
        out = run(tmp_path)
        assert "pixi run" in out and "npm run" in out


class TestRendering:
    def test_aggregate_task_is_not_shown_as_its_first_dependency(self, tmp_path: Path):
        """Taking the first quoted string out of an inline table rendered
        `all` as though it were `format`."""
        (tmp_path / "pixi.toml").write_text(
            '[tasks]\nformat = "ruff format ."\n'
            'all = { depends-on = ["format", "lint"] }\n'
        )
        out = run(tmp_path)
        assert "runs: format, lint" in out

    def test_inline_table_with_cmd_shows_the_command(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text(
            '[tasks]\nt = { cmd = "pytest -q", env = { A = "1" } }\n'
        )
        assert "pytest -q" in run(tmp_path)

    def test_task_count_is_capped(self, tmp_path: Path):
        body = "\n".join(f'task{i} = "echo {i}"' for i in range(30))
        (tmp_path / "pixi.toml").write_text(f"[tasks]\n{body}\n")
        out = run(tmp_path)
        assert "and 10 more" in out
        assert "task29" not in out

    def test_long_definitions_are_truncated(self, tmp_path: Path):
        (tmp_path / "pixi.toml").write_text(f'[tasks]\nx = "{"a" * 200}"\n')
        assert "..." in run(tmp_path)
        assert "a" * 200 not in run(tmp_path)
