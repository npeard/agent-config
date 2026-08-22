#!/usr/bin/env python
"""Verify a project is in a fit state to start work in.

Implements the master CLAUDE.md's "Step 0" as one command, so the check
costs a single tool call rather than a handful of agent turns: pre-commit
wired up and current, tests green, on the default branch, clean tree.

Boundary with toolgaps.py, kept deliberately sharp because the two were
nearly duplicates: **preflight asks whether this repo is fit to work in
right now (state); toolgaps asks whether the project has the tooling it
should have at all (capability).** Pre-commit installation and test results
are state and belong here; "is there a type checker at all" does not.

Deliberately stdlib-only and project-agnostic -- it is meant to be copied
into new projects verbatim, per this repo's ``scripts/`` convention. It
assumes a current interpreter rather than degrading to whatever `python3`
the machine ships: every project gets a local pixi environment, and hooks
invoke that environment's python explicitly. See the interpreter check
below, which enforces the assumption instead of hoping for it.

Usage:
    python scripts/preflight.py [--with-tests] [--check-updates] [--strict]

Two checks are opt-in because the common caller is a fast, possibly
offline SessionStart hook:

``--with-tests``
    Actually run the detected test command. Off by default because a suite
    can take minutes; the default merely reports what it *would* run.
``--check-updates``
    Query upstream for newer pre-commit hook revs. Off by default because
    it needs network and costs a ``git ls-remote`` per configured repo.

Exit status is 0 unless ``--strict`` is passed, so that a hook can never
abort a session over a warning.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, label: str, detail: str = "") -> None:
        self.rows.append((status, label, detail))

    def render(self) -> int:
        width = max(len(s) for s, _, _ in self.rows)
        for status, label, detail in self.rows:
            line = f"[{status:<{width}}] {label}"
            print(f"{line}: {detail}" if detail else line)
        counts = {s: sum(1 for r in self.rows if r[0] == s) for s in (OK, WARN, FAIL)}
        print(
            f"\n{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)"
        )
        return counts[FAIL] + counts[WARN]


def git(*args: str) -> str | None:
    """Run a git command, returning None rather than raising on failure."""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=20
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        # A deadline matters because --check-updates runs one ls-remote per
        # configured repo, and on a captive portal those block indefinitely.
        return None
    return out.stdout.strip()


def check_repo(report: Report) -> bool:
    if git("rev-parse", "--is-inside-work-tree") != "true":
        report.add(FAIL, "git repository", "not inside a work tree")
        return False
    report.add(OK, "git repository")
    return True


def default_branch(root: Path | None = None) -> str:
    """Best-effort default-branch name, without assuming a remote exists.

    `root` scopes the lookup to a specific checkout. check_audit_owed needs
    that: resolved from the process cwd instead, it answered about whichever
    repo preflight was invoked from.
    """
    at = ("-C", str(root)) if root else ()
    head = git(*at, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head.split("/", 1)[-1]
    for candidate in ("main", "master"):
        if git(*at, "rev-parse", "--verify", "--quiet", f"refs/heads/{candidate}"):
            return candidate
    return "main"


def check_branch(report: Report) -> None:
    current, target = git("rev-parse", "--abbrev-ref", "HEAD"), default_branch()
    if current == target:
        report.add(OK, "on default branch", current)
    else:
        # A feature branch is normal mid-task, so this is informational --
        # it only matters when starting fresh work.
        report.add(WARN, "on default branch", f"on '{current}', not '{target}'")


def check_clean_tree(report: Report) -> None:
    dirty = git("status", "--porcelain")
    if dirty is None:
        report.add(FAIL, "clean working tree", "could not read status")
    elif dirty:
        n = len(dirty.splitlines())
        report.add(WARN, "clean working tree", f"{n} uncommitted change(s)")
    else:
        report.add(OK, "clean working tree")


def declared_floor(root: Path) -> tuple[int, int] | None:
    """The project's minimum Python, from pixi.toml or pyproject.toml."""
    for name, key in (("pixi.toml", "python"), ("pyproject.toml", "requires-python")):
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        # Anchored to a line start: unanchored, `python` matched the tail of
        # `ipython = ">=8.0"` and read as a floor of 8.0 -- and a failure here
        # short-circuits every later check.
        match = re.search(
            rf'^\s*{key}\s*=\s*["\x27][^"\x27]*?(\d+)\.(\d+)',
            text,
            re.MULTILINE,
        )
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def check_interpreter(report: Report, root: Path) -> None:
    """Verify the interpreter is project-local and current.

    Every project gets a local environment with a recent interpreter, rather
    than inheriting whatever `python3` the machine ships -- on macOS that is
    still 3.9, which quietly pushes scripts and hooks towards contortions
    for a constraint nobody chose. Checking it here makes the requirement
    mechanical instead of a line of prose that decays.
    """
    running = sys.version_info[:2]
    prefix = Path(sys.prefix).resolve()
    local = root.resolve() in prefix.parents or prefix == root.resolve()
    version = f"{running[0]}.{running[1]}"

    if not local:
        # A failure, not a warning: every project is meant to carry its own
        # environment, and an inherited interpreter is how scripts end up
        # contorted for whatever version the machine happens to ship.
        report.add(
            FAIL,
            "interpreter",
            f"{version} from {prefix} is not a project-local env "
            "(run via the project's task runner)",
        )
        return

    floor = declared_floor(root)
    if floor is None:
        report.add(WARN, "interpreter", f"{version}, but no floor is declared")
    elif running < floor:
        report.add(
            FAIL,
            "interpreter",
            f"{version} is below the declared floor {floor[0]}.{floor[1]}",
        )
    else:
        report.add(
            OK, "interpreter", f"{version}, local env, floor {floor[0]}.{floor[1]}"
        )


def check_precommit_installed(report: Report, root: Path) -> None:
    if not (root / ".pre-commit-config.yaml").is_file():
        report.add(WARN, "pre-commit configured", "no .pre-commit-config.yaml")
        return
    report.add(OK, "pre-commit configured")

    # Resolve via git rather than assuming root/".git" is a directory: in a
    # worktree or submodule it is a file pointing elsewhere, and the hooks
    # live in the parent repo.
    # Run with -C so the returned path is relative to root rather than to
    # wherever this process happens to have been invoked from.
    hook_path = git("-C", str(root), "rev-parse", "--git-path", "hooks/pre-commit")
    hook = (root / hook_path) if hook_path else None
    if hook and hook.is_file() and "pre-commit" in hook.read_text(errors="replace"):
        report.add(OK, "pre-commit hook installed")
    else:
        report.add(FAIL, "pre-commit hook installed", "run: pre-commit install")


def configured_revs(config: Path) -> list[tuple[str, str]]:
    """Pair each configured repo URL with its pinned rev.

    Keys are collected independently and paired by position rather than by
    requiring `rev:` to follow `repo:` immediately. pre-commit accepts either
    order and permits other keys between them, and a stricter reader silently
    dropped whole entries -- which then read as "hook revs current" while an
    unchecked repo went stale.

    Regex rather than a YAML parse to keep this stdlib-only; a miss degrades
    to zero pairs, which the caller reports as "cannot check".
    """
    keys: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(config.read_text(errors="replace").splitlines()):
        stripped = line.strip().lstrip("-").strip()
        for kind in ("repo", "rev"):
            prefix = f"{kind}:"
            if stripped.startswith(prefix):
                value = stripped[len(prefix) :].strip().strip("'\"")
                if value:
                    keys.append((lineno, kind, value))
                break

    repos = [(i, v) for i, kind, v in keys if kind == "repo"]
    revs = [(i, v) for i, kind, v in keys if kind == "rev"]

    pairs: list[tuple[str, str]] = []
    consumed: set[int] = set()
    for position, (lineno, url) in enumerate(repos):
        # An entry's rev lies between the previous repo key and the next one,
        # on either side of the repo key itself.
        lower = repos[position - 1][0] if position else -1
        upper = repos[position + 1][0] if position + 1 < len(repos) else 10**9
        candidates = [
            (i, v) for i, v in revs if lower < i < upper and i not in consumed
        ]
        if candidates and url.startswith("http"):
            # Consume the match: without this, an entry whose rev precedes its
            # repo left that rev available to the *next* entry, which then
            # reported the wrong pin.
            consumed.add(candidates[0][0])
            pairs.append((url, candidates[0][1]))
    return pairs


def latest_tag(url: str) -> tuple[str | None, str | None]:
    """(newest semver tag, problem) -- exactly one of the two is set.

    The two failure modes are reported separately because they point the
    reader somewhere different: "unreachable" means check the network,
    while "no-semver-tags" means this repo pins something this parser
    cannot compare and the rev must be checked by hand. Collapsing both to
    None diagnosed a repo tagged `v1.0` as a network problem.
    """
    out = git("ls-remote", "--tags", "--refs", url)
    if out is None:
        return None, "unreachable"
    if not out:
        # Reachable, exit 0, no tags at all. Not a network problem, and
        # reporting it as one sends the reader to the wrong place.
        return None, "no-semver-tags"
    tags = [line.rsplit("/", 1)[-1] for line in out.splitlines()]

    def key(tag: str) -> tuple[int, ...] | None:
        m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
        return tuple(int(g) for g in m.groups()) if m else None

    ranked = sorted((k, t) for t in tags if (k := key(t)) is not None)
    if not ranked:
        return None, "no-semver-tags"
    return ranked[-1][1], None


def check_hook_revs(report: Report, root: Path) -> None:
    config = root / ".pre-commit-config.yaml"
    if not config.is_file():
        return
    configured = configured_revs(config)
    if not configured:
        # The regex found nothing, so there is no basis for a clean answer.
        # Reporting "current" here would be a false pass on a config style
        # this parser does not recognize.
        report.add(WARN, "hook revs current", "could not parse any repo/rev pairs")
        return

    stale, unreachable, untagged = [], [], []
    for url, rev in configured:
        name = url.rsplit("/", 1)[-1]
        latest, problem = latest_tag(url)
        if problem == "unreachable":
            # --check-updates is opt-in precisely because it needs network,
            # so a failed lookup is surfaced rather than folded into "ok".
            unreachable.append(name)
        elif problem == "no-semver-tags":
            untagged.append(name)
        elif latest and latest.lstrip("v") != rev.lstrip("v"):
            stale.append(f"{name} {rev} -> {latest}")
    if stale:
        report.add(
            WARN, "hook revs current", "; ".join(stale) + " (pre-commit autoupdate)"
        )
    elif unreachable:
        report.add(
            WARN, "hook revs current", f"lookup failed: {', '.join(unreachable)}"
        )
    elif untagged:
        report.add(
            WARN,
            "hook revs current",
            f"no comparable tags, check by hand: {', '.join(untagged)}",
        )
    else:
        report.add(OK, "hook revs current")


def _pixi_has_test_task(path: Path) -> bool:
    """Whether pixi.toml defines a `test` task.

    tomllib is imported here rather than at module scope for one specific
    reason: this script has to be able to *run* on an interpreter too old to
    have it, so that check_interpreter can report that fact instead of the
    module dying on import. A diagnostic that cannot execute under the
    condition it diagnoses is useless.
    """
    import tomllib

    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return False
    tasks = dict(data.get("tasks", {}))
    for feature in data.get("feature", {}).values():
        tasks.update(feature.get("tasks", {}))
    return "test" in tasks


def _npm_has_test_script(path: Path) -> bool:
    try:
        return "test" in json.loads(path.read_text()).get("scripts", {})
    except (ValueError, OSError):
        return False


def _mentions_test(path: Path) -> bool:
    """Crude fallback for formats with no cheap stdlib parser (YAML)."""
    return "test" in path.read_text()


# Priority order: a project's own task runner knows more than a bare pytest
# invocation does (env activation, flags, coverage config). Each entry owns
# its own detector, so adding a runner is one line here and nothing else.
TEST_RUNNERS = (
    ("pixi.toml", "pixi run test", _pixi_has_test_task),
    ("Taskfile.yml", "task test", _mentions_test),
    ("package.json", "npm test", _npm_has_test_script),
)


def check_friction(report: Report, root: Path) -> None:
    """Surface recurring workflow friction, if the miner is present.

    Silent when friction.py is absent: preflight is meant to be copied into
    projects that have no such script, and a missing optional companion is
    not a finding about the project.
    """
    miner = Path(__file__).resolve().parent / "friction.py"
    if not miner.is_file():
        return
    try:
        out = subprocess.run(
            [sys.executable, str(miner), "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        data = json.loads(out.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        report.add(WARN, "friction", "could not run friction.py")
        return

    if warning := data.get("ledger_warning"):
        report.add(WARN, "friction", warning)
    # Surface the denominator. A check that reports only actionable_count
    # hides its own coverage: while BENIGN_EXIT was mis-anchored, 45 of 61
    # errors were filed as benign, unclassified read a reassuring 5, and
    # preflight printed "nothing over the bar" over a classifier that could
    # not see three quarters of its input.
    seen = data.get("errors_seen", 0)
    unclassified = data.get("unclassified", 0)
    if seen and unclassified * 4 >= seen:
        report.add(
            WARN,
            "friction",
            f"{unclassified}/{seen} errors match no class; the classifier is "
            "behind its input (pixi run friction --all)",
        )
    n = data.get("actionable_count", 0)
    if n:
        classes = ", ".join(data.get("actionable", [])[:3])
        more = "..." if n > 3 else ""
        report.add(
            WARN,
            "friction",
            f"{n} class(es) over bar: {classes}{more} (pixi run friction)",
        )
    else:
        report.add(OK, "friction", "nothing over the bar")


def check_audit_owed(report: Report, root: Path) -> None:
    """Report a config audit this branch owes but has not run.

    Branch state. Each marker line is `<branch>\t<asset>`, because the
    obligation is an audit for what *this* branch changed -- unscoped, the
    warning follows you to an unrelated branch and clearing it there discards
    the original branch's obligation. The marker is gitignored and untracked,
    so no test can gate it and it does not travel between machines. Reported
    here because session start is when it matters: the hook that wrote it
    injected its reminder into a session that has since ended.

    The two-field format is parsed here rather than fetched from
    audit_assets.py. Shelling out put a subprocess in a startup check, and it
    silently ignored `root` besides -- that script resolves its own repo from
    __file__, so this reported the wrong tree whenever the two differed.
    audit_assets.py owns writing and clearing; this only reads.

    Silent when nothing is owed for the current branch, and silent in projects
    with no audit script, since preflight is copied into repos that have no
    such concept.
    """
    if not (Path(__file__).resolve().parent / "audit_assets.py").is_file():
        return
    marker = root / ".audit-owed"
    if not marker.is_file():
        return
    try:
        lines = [ln for ln in marker.read_text().splitlines() if ln.strip()]
    except OSError:
        return
    # -C root, like check_precommit_installed. Reading the branch from the
    # process cwd made this report on whichever repo preflight happened to be
    # invoked from, and made its own tests depend on the branch the checkout
    # was on -- two of them failed on `main`, which is precisely the state
    # step 0 requires to be green.
    branch = git("-C", str(root), "rev-parse", "--abbrev-ref", "HEAD") or ""
    # On the default branch, report every branch's entries, not just this one's.
    # An obligation recorded against feat/x whose work has been merged is now an
    # obligation about the default branch's contents, and reporting only
    # matching lines meant merging without auditing lost it silently.
    on_default = bool(branch) and branch == default_branch(root)
    assets = set()
    for line in lines:
        recorded, _, asset = line.partition("\t")
        # An unscoped line predates branch scoping; the safe reading of an
        # obligation with no recorded owner is that it is still owed.
        if not asset:
            assets.add(recorded)
        elif on_default or recorded == branch:
            assets.add(asset)
    if not assets:
        return
    report.add(
        WARN,
        "audit",
        f"{len(assets)} config asset(s) changed on this branch; "
        "run `pixi run audit` and the config-audit skill before integrating",
    )


def check_hooks(report: Report, root: Path) -> None:
    """Report hooks declared in the repo but not registered on this machine.

    Registration is machine state, not repo state -- a fresh clone correctly
    has none -- so it cannot be gated by a test. Session start is when it
    matters, because an unregistered hook is silently absent rather than
    broken. Silent when the repo has no registrar, since preflight is copied
    into projects that have no hooks at all.
    """
    registrar = Path(__file__).resolve().parent / "register_hooks.py"
    if not registrar.is_file():
        return
    try:
        out = subprocess.run(
            [sys.executable, str(registrar), "--check"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        report.add(WARN, "hooks registered", "could not run register_hooks.py")
        return

    if out.returncode == 0:
        report.add(
            OK,
            "hooks registered",
            out.stdout.strip().splitlines()[-1:][0]
            if out.stdout.strip()
            else "all current",
        )
        return
    drift = [line.strip() for line in out.stdout.splitlines() if line.startswith("  ")]
    report.add(
        WARN,
        "hooks registered",
        f"{len(drift)} out of date: {'; '.join(drift[:2])} (./install.sh)",
    )


def detect_test_command(root: Path) -> str | None:
    for filename, command, defines_test in TEST_RUNNERS:
        path = root / filename
        if path.is_file() and defines_test(path):
            return command
    if (root / "tests").is_dir() or list(root.glob("test_*.py")):
        return "pytest"
    return None


def check_tests(report: Report, root: Path, run: bool) -> None:
    command = detect_test_command(root)
    if command is None:
        report.add(WARN, "tests", "no test suite configured")
        return
    if not run:
        report.add(OK, "tests", f"'{command}' detected (use --with-tests to run)")
        return
    try:
        result = subprocess.run(command.split(), cwd=root, check=False)
    except FileNotFoundError:
        report.add(FAIL, "tests", f"'{command}' not found on PATH")
        return
    if result.returncode == 0:
        report.add(OK, "tests", f"'{command}' passed")
    else:
        report.add(FAIL, "tests", f"'{command}' failed (exit {result.returncode})")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-tests", action="store_true", help="run the suite")
    parser.add_argument(
        "--check-updates", action="store_true", help="query upstream hook revs"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit nonzero on any warning or failure"
    )
    parser.add_argument(
        "--no-friction",
        action="store_true",
        help="skip the friction report (on by default: local and fast)",
    )
    args = parser.parse_args(argv)

    report = Report()
    if not check_repo(report):
        report.render()
        return 1 if args.strict else 0

    root = Path(git("rev-parse", "--show-toplevel") or ".")
    check_interpreter(report, root)
    if any(status == FAIL for status, _, _ in report.rows):
        # A wrong interpreter makes every later result untrustworthy, and
        # some of them unrunnable. Report and stop rather than guessing.
        report.render()
        return 1 if args.strict else 0

    check_branch(report)
    check_clean_tree(report)
    check_precommit_installed(report, root)
    if args.check_updates:
        check_hook_revs(report, root)
    check_tests(report, root, run=args.with_tests)
    check_hooks(report, root)
    if not args.no_friction:
        check_friction(report, root)
    check_audit_owed(report, root)

    problems = report.render()
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
