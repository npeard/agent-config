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
are inspected. Known false negatives (all fail open): a command hidden in
`bash -c '...'` is one quoted word; caps set in a pixi activation env or via
threadpoolctl in a conftest are invisible, so such a repo costs one denied
round trip before the explicit caps are accepted.
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
# Wrappers that run the next command; `time` is also a benchmark signal. The
# value is the options that consume the following word, so it is not mistaken
# for the command (`nice -n 10 pytest`, `env -u NAME pytest`).
WRAPPERS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S"},
    "nohup": set(),
    "command": set(),
    "time": {"-o", "--output", "-f", "--format"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"},
}
# Interpreter and package-manager options that consume the following word.
VALUE_FLAGS = frozenset(
    {"-X", "-W", "-e", "--environment", "--manifest-path", "--with", "--python"}
    | {"-p", "--project", "--directory", "--group", "--extra", "--env-file"}
)
PACKAGE_RUNNERS = frozenset({"pixi", "uv", "poetry", "hatch"})
RUNNERS = re.compile(r"python[\d.]*|pixi|uv|poetry|hatch|bash|sh|julia|Rscript|node")
XDIST_ATTACHED = re.compile(r"-n(auto|logical|[1-9]\d*)")
BENCH_NAME = re.compile(r"bench|benchmark|timing")


def unwrap(words):
    """(words after assignments and wrappers, whether `time` was among them)."""
    timed = False
    while words:
        wrapper = base(words[0])
        if ASSIGNMENT.match(words[0]):
            words = words[1:]
            continue
        if wrapper not in WRAPPERS:
            break
        timed = timed or wrapper == "time"
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in WRAPPERS[wrapper] else rest[1:]
        words = rest[1:] if wrapper == "timeout" else rest  # the duration
    return words, timed


def base(word):
    return word.replace("\\", "/").rsplit("/", 1)[-1].lower()


def entry(words):
    """What an interpreter runs: ("-m", module), ("file", path), or None for
    `-c` code or nothing, skipping flags such as `-X dev` and `-O`."""
    it = iter(words)
    for word in it:
        if word == "-c":
            return None
        if word == "-m":
            module = next(it, None)
            return ("-m", module) if module else None
        if word in VALUE_FLAGS:
            next(it, None)
        elif not word.startswith("-"):
            return ("file", word)
    return None


def is_pytest(words):
    if not words:
        return False
    head = base(words[0])
    if head in ("pytest", "py.test"):
        return True
    if RUNNERS.fullmatch(head):
        rest = words[1:]
        if head.startswith("python") and entry(rest) == ("-m", "pytest"):
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
        if word != "-m":
            continue
        marker = words[i + 1]
        if marker == "timeit":
            return True
        # Only pytest's -m is a marker expression (`git commit -m` is a
        # message), and `not benchmark` deselects the benchmarks.
        if (
            is_pytest(words)
            and re.search(r"\bbenchmark\b", marker)
            and not re.search(r"\bnot\s+benchmark\b", marker)
        ):
            return True
    # The whole path, so `benchmarks/run.py` counts; a test file does not.
    return any(
        BENCH_NAME.search(path.lower()) and not base(path).startswith("test_")
        for path in run_targets(words)
    )


def run_targets(words):
    """What the command would run: the script an interpreter opens, or the
    task/command name after `pixi run` / `uv run`. Package-manager
    subcommands, option values and `-c` code are not targets."""
    head = base(words[0])
    if head in PACKAGE_RUNNERS:
        rest = iter(words[1:])
        for word in rest:
            if word in VALUE_FLAGS:
                next(rest, None)
            elif not word.startswith("-"):
                if word != "run":
                    return []
                break
        rest = list(rest)
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in VALUE_FLAGS else rest[1:]
        return rest[:1] + (run_targets(rest) if rest[1:] else [])
    if RUNNERS.fullmatch(head):
        target = entry(words[1:])
        return [target[1]] if target else []
    return [words[0]]


def simple_commands(command):
    return [
        unwrap(words) for words in hook_lib.shell_commands(command, hook_lib.tokenize)
    ]


def uncapped_xdist(command):
    # Raw words: unwrap() strips the assignments this looks for.
    raw = hook_lib.shell_commands(command, hook_lib.tokenize)
    # Accelerate on macOS ignores OMP_NUM_THREADS and reads its own variable.
    required = ["OMP_NUM_THREADS"]
    if sys.platform == "darwin":
        required.append("VECLIB_MAXIMUM_THREADS")
    if all(
        name in os.environ or any(w.startswith(f"{name}=") for ws in raw for w in ws)
        for name in required
    ):
        return False
    return any(is_pytest(words) and uses_xdist(words) for words, _ in map(unwrap, raw))


def capped(command):
    """`command` with the thread caps exported for everything it runs.

    Always an export statement: a prefix assignment would be invalid before a
    subshell or brace group.
    """
    return f"export {CAPS}; {command.strip()}"


def loadavg():
    return os.getloadavg()


def top_processes(count):
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
    lines = "\n".join(top_processes(5))
    return (
        f"Load is high for a benchmark: 1-min {one:.1f}, 5-min {five:.1f} on "
        f"{cores} cores (limit {LOAD_FRACTION * cores:.1f}). Timings taken now "
        "will mostly measure contention. Busiest processes (%CPU, PID, command):\n"
        f"{lines}\n"
    )


def pre(command, in_subagent):
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
        if not report:
            return
        if in_subagent:
            # notify.py silences subagent permission prompts, so an ask there
            # would block with nobody told; deny and hand the decision back.
            hook_lib.deny(
                report + "Stop and report back to the orchestrator that the "
                "machine is busy; do not wait or retry."
            )
        else:
            hook_lib.ask(report + "Approve to run anyway, or deny to wait.")


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
            pre(command, bool(data.get("agent_id")))
        elif data["hook_event_name"] == "PostToolUse":
            post(command, data["duration_ms"])
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        # Fail open: a hook that tracebacks is noisier than one that declines.
        return


if __name__ == "__main__":
    main()
