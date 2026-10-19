"""The export surface: console scripts, pre-commit hooks, and their contract.

Generic over `pyproject.toml` and `.pre-commit-hooks.yaml`, so a command added
to either is covered without editing this file.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import REPO_ROOT, write

SCRIPTS = REPO_ROOT / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CONSOLE_SCRIPTS: dict[str, str] = PYPROJECT["project"]["scripts"]


def hook_entries() -> dict[str, str]:
    """Hook id -> entry command, from the file's `id:` and `entry:` lines.

    A line reader, not a YAML parser: the file is a flat list of hooks and
    pyyaml is not a dependency of this repo.
    """
    text = (REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    ids = re.findall(r"^- id: (\S+)", text, re.MULTILINE)
    entries = re.findall(r"^  entry: (.+)$", text, re.MULTILINE)
    assert len(ids) == len(entries), "every hook needs an id and an entry"
    return dict(zip(ids, entries, strict=True))


def test_every_hook_entry_is_a_console_script():
    for hook_id, entry in hook_entries().items():
        assert entry.split()[0] in CONSOLE_SCRIPTS, hook_id


def test_console_script_targets_import():
    py_modules = PYPROJECT["tool"]["setuptools"]["py-modules"]
    for command, target in CONSOLE_SCRIPTS.items():
        module, function = target.split(":")
        assert module in py_modules, command
        assert callable(getattr(importlib.import_module(module), function)), command


@pytest.mark.installs
def test_installed_commands_run(tmp_path):
    """Needs the network: pip fetches the build backend."""
    # Installed from a copy: building in place litters the repo with build/
    # and an egg-info directory.
    source = tmp_path / "source"
    shutil.copytree(
        SCRIPTS, source / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(REPO_ROOT / "pyproject.toml", source)
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    subprocess.run([str(python), "-m", "pip", "install", "-q", str(source)], check=True)
    for command in CONSOLE_SCRIPTS:
        result = subprocess.run(
            [str(bin_dir / command), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{command}: {result.stderr}"


# script -> (fixture name, fixture body)
CP1252_CASES = {
    "check_ascii": ("rho.py", "# \u03c1\n"),
    "plain_math": (
        "rho.py",
        'import matplotlib.pyplot as plt\nplt.xlabel("phi \u03c1")\n',
    ),
    "forward_refs": (
        "rho.typ",
        (FIXTURES / "forward_refs" / "forward.typ").read_text(encoding="utf-8"),
    ),
    "trivial_wrappers": ("rho.py", "def f(x):\n    return g(x)\n\n\nf(1)\nf(2)\n"),
}
SCRIPT_FILES = {"forward_refs": "check_forward_refs"}


@pytest.mark.parametrize("name", CP1252_CASES)
def test_findings_survive_cp1252_stdout(tmp_path, name):
    """A finding names a path holding a character cp1252 cannot encode."""
    filename, body = CP1252_CASES[name]
    target = write(tmp_path, f"\u03c1_{filename}", body)
    script = SCRIPTS / f"{SCRIPT_FILES.get(name, name)}.py"
    result = subprocess.run(
        [sys.executable, str(script), str(target)],
        check=False,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        cwd=tmp_path,
    )
    assert b"UnicodeEncodeError" not in result.stderr
    assert result.stdout, "the finding should reach stdout"
