"""Tests for hooks/compute-guard.py.

The silent cases carry the weight: a hook that denied `grep -n pytest` or asked
about `cat bench.md` would block ordinary work. Inputs follow the documented
hook contract: PreToolUse carries `tool_input.command`, PostToolUse adds
`duration_ms`. Load and ps are injected by patching the module's functions.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import run_hook

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "compute-guard.py"

_spec = importlib.util.spec_from_file_location("compute_guard", HOOK)
compute_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compute_guard)

CAPS = compute_guard.CAPS
REAL_TOP_PROCESSES = compute_guard.top_processes


@pytest.fixture(autouse=True)
def quiet_machine(monkeypatch):
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.setattr(compute_guard, "loadavg", lambda: (1.0, 1.0, 1.0))
    monkeypatch.setattr(compute_guard.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(compute_guard, "top_processes", lambda count: [])


def out(event, command, monkeypatch, capsys, **extra) -> dict | None:
    payload = {
        "hook_event_name": event,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        **extra,
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    compute_guard.main()
    text = capsys.readouterr().out.strip()
    return json.loads(text)["hookSpecificOutput"] if text else None


def pre(command, monkeypatch, capsys):
    return out("PreToolUse", command, monkeypatch, capsys)


def post(command, seconds, monkeypatch, capsys):
    return out("PostToolUse", command, monkeypatch, capsys, duration_ms=seconds * 1000)


@pytest.mark.parametrize(
    "command",
    [
        "pytest -n auto",
        "pytest -n 4 tests/",
        "pytest -n4",
        "python -m pytest --numprocesses=8",
        "pytest --numprocesses 8",
        "pixi run pytest -nauto",
        "cd repo && uv run pytest -n auto -q",
        "timeout 900 pytest -n 8",
        "timeout -k 5 --signal=INT 900 pytest -n 8",
        "nice pytest -n 8",
        "nice -n 10 pytest -n 8",
        "nohup pytest -n 8",
        "env -i pytest -n 8",
        "env -u FOO BAR=1 pytest -n 8",
        "time -p pytest -n 8",
        "/usr/bin/time -l pytest -n 8",
        "python -X dev -m pytest -n 4",
        "python -O -u -m pytest -n 4",
    ],
)
def test_uncapped_xdist_is_denied_with_the_capped_command(command, monkeypatch, capsys):
    block = pre(command, monkeypatch, capsys)
    assert block["permissionDecision"] == "deny"
    assert CAPS in block["permissionDecisionReason"]
    assert command in block["permissionDecisionReason"]
    assert "updatedInput" not in block


@pytest.mark.parametrize(
    "command",
    ["pytest -n 4", "cd r && pytest -n 4", "(pytest -n 4)", "{ pytest -n 4; }"],
)
def test_the_capped_command_is_exported_and_stays_valid_shell(command):
    fixed = compute_guard.capped(command)
    assert fixed == f"export {CAPS}; {command}"
    subprocess.run(["bash", "-n", "-c", fixed], check=True)


@pytest.mark.parametrize(
    "command",
    [
        "grep -n pytest tests/log.txt",
        "pytest tests/",
        "pytest -n 0",
        "pytest -k 'not slow' -x",
        f"{CAPS} pytest -n 4",
        "export OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1; pytest -n 4",
        "echo pytest -n 4",
    ],
)
def test_other_commands_are_not_denied(command, monkeypatch, capsys):
    assert pre(command, monkeypatch, capsys) is None


def test_an_exported_cap_in_the_environment_allows_xdist(monkeypatch, capsys):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("VECLIB_MAXIMUM_THREADS", "1")
    assert pre("pytest -n auto", monkeypatch, capsys) is None


def test_omp_alone_caps_off_darwin_but_not_on_it(monkeypatch, capsys):
    command = "OMP_NUM_THREADS=1 pytest -n auto"
    monkeypatch.setattr(compute_guard.sys, "platform", "linux")
    assert pre(command, monkeypatch, capsys) is None
    # Accelerate reads VECLIB_MAXIMUM_THREADS and ignores OMP.
    monkeypatch.setattr(compute_guard.sys, "platform", "darwin")
    assert pre(command, monkeypatch, capsys)["permissionDecision"] == "deny"


BENCHMARKS = [
    "hyperfine 'python a.py'",
    "python -m timeit -s 'x=1' 'x+1'",
    "pytest --benchmark-only",
    "pytest -m benchmark",
    "python scripts/bench_fft.py",
    "python benchmarks/run.py --n 5",
    "python scripts/timing_study.py",
    "pixi run bench",
    "time ./solver input.dat",
    "OMP_NUM_THREADS=1 python benchmark.py",
    "pixi run benchmark",
    "python bench_fft.py",
    "pytest -m 'benchmark and not slow'",
    "timeout 900 python bench_fft.py",
]


@pytest.mark.parametrize("command", BENCHMARKS)
def test_a_benchmark_under_heavy_load_asks_with_load_and_processes(
    command, monkeypatch, capsys
):
    monkeypatch.setattr(compute_guard, "loadavg", lambda: (9.5, 7.25, 3.0))
    monkeypatch.setattr(
        compute_guard, "top_processes", lambda count: ["99.0 123 python hog.py"]
    )
    block = pre(command, monkeypatch, capsys)
    assert block["permissionDecision"] == "ask"
    reason = block["permissionDecisionReason"]
    assert "9.5" in reason and "7.2" in reason and "8 cores" in reason
    assert "python hog.py" in reason


def test_a_subagent_is_denied_not_asked_under_heavy_load(monkeypatch, capsys):
    # notify.py silences subagent permission prompts, so an ask would hang.
    monkeypatch.setattr(compute_guard, "loadavg", lambda: (9.5, 7.25, 3.0))
    block = out("PreToolUse", "hyperfine x", monkeypatch, capsys, agent_id="agent-1")
    assert block["permissionDecision"] == "deny"
    reason = block["permissionDecisionReason"]
    assert "9.5" in reason and "busy" in reason and "Approve" not in reason


@pytest.mark.parametrize("command", BENCHMARKS)
def test_a_benchmark_under_light_load_passes(command, monkeypatch, capsys):
    assert pre(command, monkeypatch, capsys) is None


@pytest.mark.parametrize(
    "command",
    [
        "grep -rn benchmark src/",
        "cat benchmarks/README.md",
        "git add bench_notes.py",
        "pytest tests/test_timing.py",
        'git commit -m "add benchmark harness"',
        "pytest -m 'not benchmark'",
        "pixi add pytest-benchmark",
        "uv pip install pytest-benchmark",
        "uv run --with timing x.py",
        'pixi run python -c "print(timing)"',
        "python train.py",
        "ls",
    ],
)
def test_commands_that_only_mention_benchmarks_pass_under_heavy_load(
    command, monkeypatch, capsys
):
    monkeypatch.setattr(compute_guard, "loadavg", lambda: (50.0, 50.0, 50.0))
    assert pre(command, monkeypatch, capsys) is None


def test_load_at_the_threshold_passes(monkeypatch, capsys):
    monkeypatch.setattr(compute_guard, "loadavg", lambda: (4.0, 4.0, 4.0))
    assert pre("hyperfine x", monkeypatch, capsys) is None


def test_missing_loadavg_is_silent(monkeypatch, capsys):
    def unsupported():
        raise OSError

    monkeypatch.setattr(compute_guard, "loadavg", unsupported)
    assert pre("hyperfine x", monkeypatch, capsys) is None


def test_ps_output_is_ranked_by_cpu_and_truncated(monkeypatch):
    class Result:
        stdout = "%CPU PID COMMAND\n 1.0 1 init\n80.5 2 " + "x" * 300 + "\n 5.0 3 vim\n"

    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result)
    top = REAL_TOP_PROCESSES(2)
    assert top[0].startswith("80.5 2 x") and len(top[0]) <= 110
    assert top[1].startswith("5.0 3 vim")


def test_ps_failure_is_tolerated(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", boom)
    assert REAL_TOP_PROCESSES(5) == []


@pytest.mark.parametrize(
    "command",
    ["pytest tests/", "pixi run test", "pixi run test-all", "python -m pytest -x"],
)
def test_a_long_test_run_gets_context(command, monkeypatch, capsys):
    block = post(command, 300, monkeypatch, capsys)
    assert block["hookEventName"] == "PostToolUse"
    context = block["additionalContext"]
    assert (
        "300 s" in context and "--durations=15" in context and "thread caps" in context
    )


@pytest.mark.parametrize("command", ["pytest tests/", "pixi run test"])
def test_a_short_test_run_gets_no_context(command, monkeypatch, capsys):
    assert post(command, 120, monkeypatch, capsys) is None


@pytest.mark.parametrize(
    "command", ["python train.py", "grep -n pytest log", "sleep 200"]
)
def test_a_long_command_that_is_not_a_test_run_gets_no_context(
    command, monkeypatch, capsys
):
    assert post(command, 600, monkeypatch, capsys) is None


@pytest.mark.parametrize("body", ["", "not json", "[1]", "null"])
def test_unusable_stdin_is_silent_with_a_clean_exit(body):
    assert run_hook(HOOK, body) == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"hook_event_name": "PreToolUse", "tool_name": "Bash"},
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"command": "pytest -n 4"},
        },
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
        },
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": 5},
        },
    ],
)
def test_malformed_or_foreign_input_is_silent(payload):
    assert run_hook(HOOK, payload) == ""


def test_the_deny_contract_holds_as_a_subprocess():
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -n auto"},
    }
    block = json.loads(run_hook(HOOK, payload))["hookSpecificOutput"]
    assert block["permissionDecision"] == "deny"
