"""The export surface: console scripts, pre-commit hooks, and their contract.

Read from `pyproject.toml` and `.pre-commit-hooks.yaml`, so a command or hook
added to either is checked here without editing this file -- except the cp1252
test, which needs a case per command and fails until a new one has it.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import shutil
import socket
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


def siblings(module: str) -> set[str]:
    """The scripts/ modules `module` needs beside it once installed.

    Those it imports or loads by path through a load_sibling helper. An
    import guarded by a check for its file ("audit_assets.py") is an optional
    companion that preflight skips when absent, so it is not counted.
    """
    tree = ast.parse((SCRIPTS / f"{module}.py").read_text(encoding="utf-8"))
    imported, loaded, guarded = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Constant) and str(node.value).endswith(".py"):
            guarded.add(node.value.removesuffix(".py"))
        elif isinstance(node, ast.Call) and getattr(
            node.func, "attr", getattr(node.func, "id", None)
        ) in ("load_sibling", "_load_sibling"):
            loaded.add(node.args[0].value)
    names = (imported - guarded) | loaded
    return {name for name in names if (SCRIPTS / f"{name}.py").is_file()}


def test_every_module_an_export_needs_is_packaged():
    """A sibling left out of py-modules imports fine here, from scripts/,
    and is missing, or for preflight silently skipped, once installed."""
    py_modules = set(PYPROJECT["tool"]["setuptools"]["py-modules"])
    pending = [target.split(":")[0] for target in CONSOLE_SCRIPTS.values()]
    needed = set()
    while pending:
        module = pending.pop()
        if module not in needed:
            needed.add(module)
            pending += siblings(module)
    assert needed <= py_modules, sorted(needed - py_modules)


def test_installed_commands_run(tmp_path):
    """Offline: --no-index proves it, and the dev env supplies setuptools."""
    # Installed from a copy: building in place litters the repo with build/
    # and an egg-info directory.
    source = tmp_path / "source"
    shutil.copytree(
        SCRIPTS, source / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy(REPO_ROOT / "pyproject.toml", source)
    venv = tmp_path / "venv"
    # System site-packages so the build sees the env's setuptools without a
    # download; the commands still land in, and run from, the venv.
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)], check=True
    )
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    subprocess.run(
        [
            *(str(python), "-m", "pip", "install", "-q"),
            *("--no-index", "--no-build-isolation", str(source)),
        ],
        check=True,
    )
    for command in CONSOLE_SCRIPTS:
        result = subprocess.run(
            [str(bin_dir / command), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{command}: {result.stderr}"


RHO = "\u03c1"


def one_file(name: str, body: str):
    return lambda root: [str(write(root, f"{RHO}_{name}", body))]


def report_dir(root: Path) -> list[str]:
    report = root / RHO
    (report / "figures").mkdir(parents=True)
    write(report, "Snakefile", 'FIGURES = {"example": "plot_example"}\n')
    write(report, "report.typ", "")
    return [str(report)]


def rho_branch(root: Path) -> list[str]:
    subprocess.run(["git", "checkout", "-q", "-b", RHO], cwd=root, check=True)
    return ["--no-friction", "--offline"]


LISTENERS: list[socket.socket] = []


def jupyter_listening(root: Path) -> list[str]:
    """A held-open local port, so the run reports it and launches no Lab."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    LISTENERS.append(sock)
    port = str(sock.getsockname()[1])
    return [*("--port", port, "--token", RHO, "--timeout", "1", "--root", str(root))]


# command -> its argv, given a fresh git repo, for a run whose output names RHO
CP1252_CASES = {
    "check-ascii": one_file("rho.py", f"# {RHO}\n"),
    "plain-math": one_file(
        "rho.py", f'import matplotlib.pyplot as plt\nplt.xlabel("phi {RHO}")\n'
    ),
    "forward-refs": one_file(
        "rho.typ",
        (FIXTURES / "forward_refs" / "forward.typ").read_text(encoding="utf-8"),
    ),
    "trivial-wrappers": one_file(
        "rho.py", "def f(x):\n    return g(x)\n\n\nf(1)\nf(2)\n"
    ),
    "preflight": rho_branch,
    "new-report": lambda root: [
        *(str(root / RHO), "--shared", str(root / "shared")),
        *("--title", "T"),
    ],
    "report-check": report_dir,
    "jupyter-mcp": jupyter_listening,
}


@pytest.mark.parametrize("command", CONSOLE_SCRIPTS)
def test_output_survives_cp1252_stdout(git_repo, command):
    """Output naming a path or branch that cp1252 cannot encode still prints.

    Over every console script, so a new one fails here until it has a case,
    and so cannot ship without its stdout reconfigure line.
    """
    assert command in CP1252_CASES, f"add a cp1252 case for {command}"
    argv = CP1252_CASES[command](git_repo)
    module = CONSOLE_SCRIPTS[command].split(":")[0]
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / f"{module}.py"), *argv],
        check=False,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        cwd=git_repo,
    )
    assert b"UnicodeEncodeError" not in result.stderr
    assert result.stdout, "the output should reach stdout"


def test_readme_lists_the_exports():
    """The README's lists are the compatibility promise, so they must not drift.

    Every hook is a row of the hook table; every command is either a hook
    (the gates share their names) or one of the bullets after it.
    """
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    start = text.index("## Using these tools from another project")
    section = text[start : text.index("\n## ", start + 1)]
    table = section[section.index("| Hook") :].split("\n\n")[0]
    hooks = set(re.findall(r"^\| `([^`]+)`", table, re.MULTILINE))
    bullets = set(re.findall(r"^- `([\w-]+)[^`]*`\s+--", section, re.MULTILINE))
    assert hooks == set(hook_entries())
    assert hooks | bullets == set(CONSOLE_SCRIPTS)
