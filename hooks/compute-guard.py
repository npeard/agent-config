#!/usr/bin/env python3
# claude-hook: PreToolUse Bash
# claude-hook: PostToolUse Bash
"""Keep shared-machine compute honest: thread caps, a load gate, slow-test notice.

Transcript mining over 14 days and four projects found 1,222 pytest runs
(91 over 120 s, 23 at the 600 s cap), load averages to 238 on 12 cores, and 68
of 93 long benchmark runs with no load check before them. The agents found the
contention only afterwards. compute-job-safety states the rules; this enforces
the three that a command line can show.

PreToolUse: `pytest -n N` without OMP_NUM_THREADS in the command is denied with
the capped command to re-issue (each xdist worker otherwise starts a thread per
core in numpy/torch: 12 workers drove load to 136). Not rewritten through
updatedInput, which would bypass the permission system.

PreToolUse: a benchmark/timing command while the 1-minute load average exceeds
half the cores asks the user, showing the busiest processes, because timings
taken on a loaded machine are meaningless and the user may want to defer.

PostToolUse: a test run that took over SLOW_TEST_SECONDS gets a note, using the
`duration_ms` the host supplies (so no start time is stored).

Commands are tokenized, so `grep -n pytest` or `cat bench.md` never matches:
only the command word, and for interpreters and task runners their arguments,
are inspected. Known false negative: a command hidden in `bash -c '...'` is one
quoted word, so it passes (fails open).
"""

import json
import os
import re
import sys

import hook_lib

SLOW_TEST_SECONDS = 120
LOAD_FRACTION = 0.5
CAPS = (
    "OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 "
    "VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1"
)

ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
# Wrappers that run the next word; `time` is also a benchmark signal.
WRAPPERS = frozenset({"env", "nohup", "command", "time"})
RUNNERS = re.compile(r"python[\d.]*|pixi|uv|poetry|hatch|bash|sh|julia|Rscript|node")
XDIST_ATTACHED = re.compile(r"-n(auto|logical|[1-9]\d*)")
BENCH_NAME = re.compile(r"bench|benchmark|timing")


def unwrap(words):
    """(words after assignments and wrappers, whether `time` was among them)."""
    timed = False
    while words and (ASSIGNMENT.match(words[0]) or words[0] in WRAPPERS):
        timed = timed or words[0] == "time"
        words = words[1:]
    return words, timed


def base(word):
    return word.replace("\\", "/").rsplit("/", 1)[-1].lower()


def is_pytest(words):
    if not words:
        return False
    head = base(words[0])
    if head in ("pytest", "py.test"):
        return True
    if RUNNERS.fullmatch(head):
        rest = words[1:]
        if head.startswith("python") and rest[:1] == ["-m"] and rest[1:2] == ["pytest"]:
            return True
        # `pixi run pytest`, `uv run python -m pytest`, `pixi run test-fast`
        if "run" in rest:
            after = rest[rest.index("run") + 1 :]
            return any(
                base(w) in ("pytest", "py.test") or re.fullmatch(r"test[\w:-]*", w)
                for w in after
            )
    return False


def uses_xdist(words):
    for i, word in enumerate(words):
        if XDIST_ATTACHED.fullmatch(word) or word.startswith("--numprocesses="):
            return not word.endswith("=0")
        if word in ("-n", "--numprocesses") and words[i + 1 : i + 2]:
            return words[i + 1] != "0"
    return False


def is_benchmark(words, timed):
    if timed:
        return True
    if not words:
        return False
    head = base(words[0])
    if head == "hyperfine" or head == "timeit":
        return True
    if any(w.startswith("--benchmark") for w in words):
        return True
    for i, word in enumerate(words[:-1]):
        if word == "-m" and (
            words[i + 1] == "timeit" or re.search(r"\bbenchmark\b", words[i + 1])
        ):
            return True
    if RUNNERS.fullmatch(head):
        candidates = [w for w in words[1:] if not w.startswith("-")]
    else:
        candidates = [words[0]]
    # The whole path, so `benchmarks/run.py` counts; a test file does not.
    return any(
        BENCH_NAME.search(path.lower()) and not base(path).startswith("test_")
        for path in candidates
    )


def simple_commands(command):
    return [
        unwrap(words) for words in hook_lib.shell_commands(command, hook_lib.tokenize)
    ]


def uncapped_xdist(command):
    if "OMP_NUM_THREADS" in os.environ:
        return False
    # Raw words: unwrap() strips the assignments this looks for.
    raw = hook_lib.shell_commands(command, hook_lib.tokenize)
    if any(w.startswith("OMP_NUM_THREADS=") for words in raw for w in words):
        return False
    return any(is_pytest(words) and uses_xdist(words) for words, _ in map(unwrap, raw))


def capped(command):
    """`command` with the thread caps set for everything it runs."""
    command = command.strip()
    if (
        len(hook_lib.shell_commands(command, hook_lib.tokenize)) == 1
        and "\n" not in command
    ):
        return f"{CAPS} {command}"
    return f"export {CAPS}; {command}"


def loadavg():
    return os.getloadavg()


def top_processes(count=5):
    """The `count` busiest processes as ps lines; empty if ps is unusable."""
    import subprocess

    try:
        out = subprocess.run(
            ["ps", "-Ao", "pcpu,pid,command"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3 and re.fullmatch(r"\d+(\.\d+)?", parts[0]):
            rows.append((float(parts[0]), line.strip()[:110]))
    return [text for _, text in sorted(rows, reverse=True)[:count]]


def load_report():
    """A report when the machine is busy enough to spoil a timing, else None."""
    try:
        one, five, _ = loadavg()
    except (OSError, AttributeError):
        return None
    cores = os.cpu_count() or 1
    if one <= LOAD_FRACTION * cores:
        return None
    lines = "\n".join(top_processes())
    return (
        f"Load is high for a benchmark: 1-min {one:.1f}, 5-min {five:.1f} on "
        f"{cores} cores (limit {LOAD_FRACTION * cores:.1f}). Timings taken now "
        "will mostly measure contention. Busiest processes (%CPU, PID, command):\n"
        f"{lines}\nApprove to run anyway, or deny to wait."
    )


def pre(command):
    if uncapped_xdist(command):
        hook_lib.deny(
            "pytest with xdist and no thread caps: each worker would start a "
            "thread per core in numpy/torch, oversubscribing the machine "
            "(12 workers drove load to 136 on 12 cores). Re-issue as: "
            + capped(command)
        )
        return
    if any(is_benchmark(words, timed) for words, timed in simple_commands(command)):
        report = load_report()
        if report:
            hook_lib.ask(report)


def post(command, duration_ms):
    seconds = duration_ms / 1000
    if seconds <= SLOW_TEST_SECONDS:
        return
    if not any(is_pytest(words) for words, _ in simple_commands(command)):
        return
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"The test run took {seconds:.0f} s. A dev-loop test run "
                        "should finish in seconds. Before rerunning: (a) check "
                        "machine load, (b) run with --durations=15 and mark the "
                        "slowest tests `slow`, (c) check thread caps "
                        "(OMP/MKL/OPENBLAS_NUM_THREADS). See compute-job-safety."
                    ),
                }
            }
        )
    )


def main():
    try:
        data = json.load(sys.stdin)
        if data["tool_name"] != "Bash":
            return
        command = data["tool_input"]["command"]
        if data["hook_event_name"] == "PreToolUse":
            pre(command)
        elif data["hook_event_name"] == "PostToolUse":
            post(command, data["duration_ms"])
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        # Fail open: a hook that tracebacks is noisier than one that declines.
        return


if __name__ == "__main__":
    main()
