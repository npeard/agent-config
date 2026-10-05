#!/usr/bin/env python
"""Report dependency updates a pixi project could take, from either source.

An agent asked whether a newer torch existed queried only conda-forge, the
source the project locks it from, and said no, while PyPI had torch 2.14.0 with a
wheel for this machine (one research project). ``pixi upgrade`` would not
have caught it either: it looks in each package's declared source by design.
So there are two halves, and pixi owns one of them.

* **Same-source** updates are whatever ``pixi upgrade --dry-run --json``
  proposes. It is solver-aware -- it proposes only versions that resolve
  together, which per-package queries cannot know -- so this module reports
  its explicit proposals and never re-derives them. A solve failure is
  reported as the solver's own text and not retried with a guessed
  ``--exclude``: the conflict is itself worth telling the user about, and a
  retry would hide it. Nothing is ever applied or installed: every upgrade
  argv carries ``--dry-run``, and every pixi call that could install an
  environment carries ``--no-install`` (``--frozen`` alone installs).
* **Cross-source** updates are the only thing computed here: for each
  explicit locked dependency, the newest final release in the source it is
  *not* locked from (PyPI for a conda package, conda-forge for a PyPI one),
  for the current platform only, since that is where the user works.

Results are cached per project in ``.pixi/agent-drift/deps.json`` for 24 h,
and invalidated early when the lock or manifest changes. A cold check costs
~25 s on a research project, so the SessionStart hook only reads the cache (``cached``)
and, when it is stale, starts ``--refresh`` detached. That refresh holds a
pid lock next to the cache, so a second one refuses while the first is
alive, and it kills its own pixi children if it is interrupted. ``--ack``
records the reported versions so that a declined update stops being raised
until a newer release appears.

Trust boundary: the text printed here comes from PyPI, the conda channels
and the pixi solver, and it reaches an agent's context through the hook.
Only package names, versions, wheel tags and the solver's error excerpt
are emitted, each on one line, and none of it is executed or passed to a
shell. The ``--ack`` hint names only the running interpreter, this script
and the project root, each quoted.

Stdlib-only, because the SessionStart hook's interpreter is not a project
environment. ``fetch`` and ``run`` are injected so the tests never touch the
network or the real pixi; the CLI passes the real ones explicitly.

Usage:
    python scripts/dep_updates.py [PROJECT] [--refresh] [--ack] [--json]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Bootstrap: platform_paths is loaded by path, since the SessionStart hook
# runs this from any cwd, and via its own load_sibling, so a copy the hook
# or preflight already registered is the one used.
_spec = importlib.util.spec_from_file_location(
    "_platform_paths_bootstrap", Path(__file__).resolve().parent / "platform_paths.py"
)
_bootstrap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bootstrap)
platform_paths = _bootstrap.load_sibling("platform_paths")

MAPPING_URL = (
    "https://raw.githubusercontent.com/prefix-dev/parselmouth/main/files/"
    "compressed_mapping.json"
)
PYPI_JSON = "https://pypi.org/pypi/{}/json"
CACHE_SECONDS = 24 * 3600
# How long a result with unchecked items stays fresh. Long enough that a
# lasting failure (offline, say) does not relaunch a refresh at every
# SessionStart, short enough that a transient one clears the same session.
RETRY_SECONDS = 3600
MAPPING_SECONDS = 7 * 24 * 3600
REQUEST_SECONDS = 5.0
# The CLI is also the detached refresh the SessionStart hook starts, which
# nobody waits on, so the budget is generous. A cold run on a research project needs
# ~25 s, most of it `pixi list` (see _locked).
CLI_BUDGET_SECONDS = 120.0
# A lock older than this is stale whatever its pid says: the pid may have
# been reused, and on Windows a dead process whose handle is still open
# reads as alive. Five budgets, so a live refresh is never taken over.
LOCK_STALE_SECONDS = 600.0
UPGRADE = ["pixi", "upgrade", "--dry-run", "--no-install", "--json"]
# What pixi output of an unforeseen shape raises when parsed. preflight
# promises exit 0, so each parse catches these and records the step as
# unchecked instead of crashing.
MALFORMED = (KeyError, TypeError, ValueError, AttributeError, IndexError)
STDERR_LINES = 8

# PyPI wheel platform tags that install on each pixi platform.
PLATFORM_TAGS = {
    "win-64": r"win_amd64",
    "win-arm64": r"win_arm64",
    "linux-64": r"(many|musl)linux\w*_x86_64",
    "linux-aarch64": r"(many|musl)linux\w*_aarch64",
    "osx-64": r"macosx_\w+_(x86_64|universal2|intel)",
    "osx-arm64": r"macosx_\w+_(arm64|universal2)",
}

Run = Callable[[list[str], float], subprocess.CompletedProcess]
Fetch = Callable[[str], bytes]


@dataclass
class Finding:
    name: str
    pypi_name: str | None
    source: str
    locked: str
    candidate: str
    candidate_source: str
    wheel: str | None
    spec: str | None
    envs: list[str]


@dataclass
class DepReport:
    applicable: bool
    platform: str
    same_source: list[Finding]
    cross_source: list[Finding]
    solve_error: str | None
    pixi_missing: bool
    unchecked: list[str]
    notes: list[str]
    from_cache: bool


def _blank(applicable: bool, platform: str) -> DepReport:
    return DepReport(
        applicable=applicable,
        platform=platform,
        same_source=[],
        cross_source=[],
        solve_error=None,
        pixi_missing=False,
        unchecked=[],
        notes=[],
        from_cache=False,
    )


def is_clean(report: DepReport) -> bool:
    """Whether there is nothing to tell the user, degradations included.

    One definition, because render, preflight and the SessionStart hook all
    decide on it, and a note left out of one of them read as "up to date"
    while the check was running on guessed names.
    """
    return not (
        report.solve_error
        or report.pixi_missing
        or report.same_source
        or report.cross_source
        or report.unchecked
        or report.notes
    )


_RELEASE = re.compile(r"(\d+(?:\.\d+)*)(?:\.?post(\d+))?")


def version_key(version: str | None) -> tuple | None:
    """A sortable key for a final release, or None for anything else.

    None covers pre-releases, dev builds and local versions alike: none of
    them is an update worth offering, and an unparsable version must never
    win a max(). Trailing zeros are dropped so that 2.13 == 2.13.0.
    """
    match = _RELEASE.fullmatch(version or "")
    if match is None:
        return None
    release = [int(part) for part in match[1].split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    return tuple(release), int(match[2] or 0)


def _newest(versions) -> str | None:
    keyed = [(key, v) for v in versions if (key := version_key(v)) is not None]
    return max(keyed)[1] if keyed else None


def _newer(candidate: str, *baselines: str | None) -> bool:
    """Whether candidate beats every baseline; an unreadable baseline blocks."""
    key = version_key(candidate)
    for baseline in baselines:
        if baseline is None:
            continue
        base = version_key(baseline)
        if key is None or base is None or key <= base:
            return False
    return key is not None


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _manifest(root: Path) -> Path | None:
    if (root / "pixi.toml").is_file():
        return root / "pixi.toml"
    pyproject = root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return pyproject if "pixi" in data.get("tool", {}) else None


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _read_json(path: Path) -> dict | None:
    """A cached JSON object, or None when missing, corrupt or not an object.

    A refresh interrupted mid-write must read as stale, not crash the next
    session, so every failure here is simply "no cache".
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    """Write atomically, so a reader never sees half a file.

    A cache that cannot be written costs only a recompute next time, so an
    OSError is dropped rather than failing the check.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)


def _run(run: Run, argv: list[str], cap: float, deadline: float):
    timeout = min(cap, deadline - time.time())
    if timeout <= 0:
        raise subprocess.TimeoutExpired(argv, 0)
    return run(argv, timeout)


def _reason(exc: BaseException) -> str:
    timeouts = (TimeoutError, subprocess.TimeoutExpired)
    if isinstance(exc, timeouts) or isinstance(getattr(exc, "reason", None), timeouts):
        return "timed out"
    if isinstance(exc, OSError):
        return "unreachable"
    if isinstance(exc, MALFORMED):
        return "unexpected output"
    return f"failed: {type(exc).__name__}"


def _solve_excerpt(stderr: str) -> str:
    """The solver's message, flattened to ASCII, from ``Error`` to ``help:``.

    pixi draws its error as a tree of box characters, which a cp1252
    Windows console cannot print; the words survive the ASCII filter. WARN
    lines before the error (a stray PIXI_PROJECT_MANIFEST, say) are noise.
    """
    lines = [
        " ".join(raw.encode("ascii", "ignore").decode().split())
        for raw in stderr.splitlines()
    ]
    start = next((i for i, line in enumerate(lines) if line.startswith("Error")), 0)
    kept = []
    for line in lines[start:]:
        if line.startswith("help:"):
            break
        if line:
            kept.append(line)
    return " ".join(kept[:STDERR_LINES])


def _side_version(side: dict) -> str:
    """A version from one side of an upgrade entry.

    PyPI sides carry it; conda sides carry only the package URL, whose file
    name is ``name-version-build.conda``.
    """
    if side.get("version"):
        return side["version"]
    stem = side["conda"].rsplit("/", 1)[-1]
    return stem.removesuffix(".conda").removesuffix(".tar.bz2").rsplit("-", 2)[1]


def _same_source(upgrade: dict, platform: str) -> list[Finding]:
    """Explicit proposals for this platform, deduplicated across envs.

    Platform keys carry a virtual-package suffix (``win-64-cuda-13-0``), so
    match on the prefix.
    """
    found: dict[str, Finding] = {}
    for env, platforms in upgrade.get("environment", {}).items():
        for key, entries in platforms.items():
            if key != platform and not key.startswith(platform + "-"):
                continue
            for entry in entries:
                if not (entry.get("explicit") and entry["before"] and entry["after"]):
                    continue
                if entry["name"] in found:
                    envs = found[entry["name"]].envs
                    envs.extend([] if env in envs else [env])
                    continue
                source = (
                    "pypi"
                    if entry["type"] == "pypi"
                    else entry["before"]["conda"].rsplit("/", 3)[1]
                )
                found[entry["name"]] = Finding(
                    name=entry["name"],
                    pypi_name=None,
                    source=source,
                    locked=_side_version(entry["before"]),
                    candidate=_side_version(entry["after"]),
                    candidate_source=source,
                    wheel=None,
                    spec=None,
                    envs=[env],
                )
    return sorted(found.values(), key=lambda f: f.name)


def _valid_row(pkg) -> bool:
    """Whether a listed package has every field the checks read."""
    if not isinstance(pkg, dict):
        return False
    fields = ["name", "version", "kind"] + (
        ["source"] if pkg.get("kind") == "conda" else []
    )
    return all(isinstance(pkg.get(field), str) for field in fields)


def _valid_listing(locked) -> bool:
    return isinstance(locked, dict) and all(
        isinstance(entry, list) and len(entry) == 2 and _valid_row(entry[0])
        for entry in locked.values()
    )


def _env_rows(result: subprocess.CompletedProcess) -> list[dict]:
    result.check_returncode()
    # An editable path dependency has no version, and nothing to update.
    rows = [pkg for pkg in json.loads(result.stdout) if pkg.get("version") is not None]
    if not all(_valid_row(pkg) for pkg in rows):
        raise ValueError("a pixi list row lacks the expected fields")
    return rows


def _locked(pool, run: Run, info: dict, platform: str, deadline: float):
    """Explicit locked packages by name, as ``[package, envs]``, and the envs
    that could not be listed.

    Only envs solved for this platform are listed, matched on ``subdir``
    because the platform ``name`` carries any virtual-package suffix
    (``win-64-cuda-13-0``). They are listed in parallel because ``pixi
    list`` is slow on a project with an editable path dependency (~21 s per
    env on one project, against 0.2 s without one). One env failing does not
    discard the others.
    """
    jobs = [
        (
            env["name"],
            pool.submit(
                _run,
                run,
                [
                    *("pixi", "list", "--json", "--explicit", "--frozen"),
                    *("--no-install", "-e", env["name"]),
                ],
                math.inf,
                deadline,
            ),
        )
        for env in info["environments_info"]
        if any(p.get("subdir") == platform for p in env.get("platforms") or [])
    ]
    locked: dict[str, list] = {}
    unchecked = []
    for env, job in jobs:
        try:
            rows = _env_rows(job.result(timeout=max(0.0, deadline - time.time())))
        except (OSError, subprocess.SubprocessError, *MALFORMED) as exc:
            unchecked.append(f"pixi list -e {env} ({_reason(exc)})")
            continue
        for pkg in rows:
            locked.setdefault(pkg["name"], [pkg, []])[1].append(env)
    return locked, unchecked


def _mapping(root: Path, fetch: Fetch, now: float) -> dict:
    """prefix.dev's conda -> PyPI name mapping, the one pixi itself uses."""
    path = root / ".pixi" / "agent-drift" / "mapping.json"
    cached = _read_json(path)
    if cached is not None:
        fetched_at, mapping = cached.get("fetched_at"), cached.get("mapping")
        fresh = isinstance(fetched_at, int | float) and isinstance(mapping, dict)
        if fresh and 0 <= now - fetched_at < MAPPING_SECONDS:
            return mapping
    mapping = json.loads(fetch(MAPPING_URL))
    _write_json(path, {"fetched_at": now, "mapping": mapping})
    return mapping


def _pypi_identity(pkg: dict, mapping: dict | None) -> str | None:
    """The PyPI name of a conda package, or None when it has none.

    A metapackage maps to null (``pytorch-gpu``); its identity is a mapped
    dependency pinned to its own version (``pytorch 2.13.0 cuda*`` ->
    ``torch``). The pin is what marks a metapackage: ``python`` depends on
    ``pip`` too, and taking any mapped dependency reported pip's releases
    as python's. One hop only, so ``cuda-version`` stays unmapped.
    """
    if mapping is None:
        return pkg["name"]
    target = mapping.get(pkg["name"])
    if target:
        return target
    for dep in pkg.get("depends") or []:
        parts = dep.split()
        if len(parts) >= 2 and parts[1].removeprefix("==") == pkg["version"]:
            target = mapping.get(parts[0])
            if target:
                return target
    return None


def _conda_identity(pypi_name: str, reverse: dict[str, list[str]]) -> str:
    """The conda name of a PyPI package: the mapping's, else the lowercased name.

    Lowercased and not PEP 503-normalized, because conda-forge keeps PyPI's
    separators: ``pixi search`` finds ``ruamel.yaml`` and ``zope.interface``
    on win-64 and exits 1 for ``ruamel-yaml`` and ``zope-interface``
    (checked 2026-09-23), so normalizing reported both as absent.
    """
    name = pypi_name.lower()
    candidates = reverse.get(_normalize(pypi_name), [])
    return name if name in candidates or not candidates else candidates[0]


def _python_ok(py_tag: str, abi_tag: str, python: tuple[int, int] | None) -> bool:
    if python is None:
        return py_tag == "py3" and abi_tag == "none"
    major, minor = python
    cp = f"cp{major}{minor}"
    if abi_tag == "abi3":
        match = re.fullmatch(rf"cp{major}(\d+)", py_tag)
        return match is not None and int(match[1]) <= minor
    return abi_tag in (cp, "none") and py_tag in (cp, f"py{major}", f"py{major}{minor}")


def _wheel_match(filename: str, platform: str, python) -> str | None:
    py_tags, abi_tags, plat_tags = (
        part.split(".") for part in filename.removesuffix(".whl").split("-")[-3:]
    )
    pattern = PLATFORM_TAGS.get(platform)
    plat = next(
        (
            tag
            for tag in plat_tags
            if tag == "any" or (pattern and re.fullmatch(pattern, tag))
        ),
        None,
    )
    if plat is None:
        return None
    for py_tag in py_tags:
        for abi_tag in abi_tags:
            if _python_ok(py_tag, abi_tag, python):
                return "none-any" if plat == "any" else f"{plat} {py_tag}"
    return None


def _wheel_status(files: list[dict], platform: str, python) -> str:
    for file in files:
        if file["filename"].endswith(".whl") and not file.get("yanked"):
            match = _wheel_match(file["filename"], platform, python)
            if match:
                return f"{match} wheel"
    if any(file.get("packagetype") == "sdist" for file in files):
        return "sdist only (would build)"
    return "no wheel for this platform"


def _pypi_latest(fetch: Fetch, name: str, platform: str, python):
    try:
        data = json.loads(fetch(PYPI_JSON.format(name)))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # not on PyPI
            return None
        raise
    releases = {
        version: files
        for version, files in data["releases"].items()
        if any(not file.get("yanked") for file in files)
    }
    latest = _newest(releases)
    if latest is None:
        return None
    return "pypi", latest, _wheel_status(releases[latest], platform, python)


def _conda_latest(run: Run, name: str, platform: str, deadline: float):
    argv = ["pixi", "search", "--json", "-p", platform, name]
    result = _run(run, argv, REQUEST_SECONDS, deadline)
    if result.returncode == 1:  # not on the project's channels
        return None
    result.check_returncode()
    # Each subdir's list is its own order, so take the max over all of them
    # rather than trusting any element's position.
    rows = [row for rows in json.loads(result.stdout).values() for row in rows]
    latest = _newest(row["version"] for row in rows)
    if latest is None:
        return None
    row = next(row for row in rows if row["version"] == latest)
    channel = row.get("channel", "").rstrip("/").rsplit("/", 1)[-1]
    return channel or "conda", latest, None


def _spec(pkg: dict) -> str | None:
    spec = pkg.get("requested_spec")
    return spec.strip('"') if spec else None


def _cross_source(pool, locked, mapping, fetch, run, platform, deadline):
    """Findings from the other source, plus what could not be checked."""
    python_pkg = locked.get("python", ({}, []))[0]
    minor = re.match(r"(\d+)\.(\d+)", python_pkg.get("version", ""))
    python = (int(minor[1]), int(minor[2])) if minor else None
    reverse: dict[str, list[str]] = {}
    for conda_name, pypi_name in (mapping or {}).items():
        if pypi_name:
            reverse.setdefault(_normalize(pypi_name), []).append(conda_name)
    jobs = []
    for pkg, envs in locked.values():
        if pkg["kind"] == "conda":
            other = _pypi_identity(pkg, mapping)
            if other is None:
                continue
            future = pool.submit(_pypi_latest, fetch, other, platform, python)
        else:
            other = _conda_identity(pkg["name"], reverse)
            future = pool.submit(_conda_latest, run, other, platform, deadline)
        jobs.append((future, pkg, envs, other))
    done, _ = concurrent.futures.wait(
        [job[0] for job in jobs], timeout=max(0.0, deadline - time.time())
    )
    findings, unchecked = [], []
    for future, pkg, envs, other in jobs:
        if future not in done:
            future.cancel()
            unchecked.append(f"{other} (budget)")
        elif future.exception() is not None:
            unchecked.append(f"{other} ({_reason(future.exception())})")
        elif (result := future.result()) is not None:
            findings.append((pkg, envs, other, *result))
    return findings, unchecked


def _compute(root, fetch: Fetch, run: Run, now, deadline, locked: dict | None):
    """A fresh report, plus the locked packages it used (None if unlisted).

    ``locked`` is a previous listing still valid for this lock, or None to
    list afresh.
    """
    empty = _blank(True, "")
    try:
        info = json.loads(
            _run(run, ["pixi", "info", "--json"], math.inf, deadline).stdout
        )
        platform = info["platform"]
        if not isinstance(platform, str) or not isinstance(
            info["environments_info"], list
        ):
            raise TypeError("pixi info lacks a platform or its environments")
    except FileNotFoundError:
        empty.pixi_missing = True
        return empty, None
    except (OSError, subprocess.SubprocessError, *MALFORMED) as exc:
        empty.unchecked.append(f"pixi info ({_reason(exc)})")
        return empty, None
    report = _blank(True, platform)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=16)
    try:
        upgrade = pool.submit(_run, run, UPGRADE, math.inf, deadline)
        mapping_job = pool.submit(_mapping, root, fetch, now)
        # Only a complete listing is kept for reuse: a partial one reused
        # under the same lock would hide the env that failed until it moved.
        reusable = locked
        if locked is None:
            try:
                locked, failed = _locked(pool, run, info, platform, deadline)
            except MALFORMED as exc:  # an environments_info entry of odd shape
                locked, failed = {}, [f"pixi list ({_reason(exc)})"]
            report.unchecked.extend(failed)
            reusable = None if failed else locked
        try:
            mapping = mapping_job.result(timeout=max(0.0, deadline - time.time()))
        except (OSError, ValueError) as exc:  # offline, timed out, or bad JSON
            mapping = None
            report.notes.append(
                f"conda/PyPI name mapping unavailable ({_reason(exc)}); "
                "cross-source names assumed identical"
            )
        found, unchecked = _cross_source(
            pool, locked or {}, mapping, fetch, run, platform, deadline
        )
        report.unchecked.extend(unchecked)
        try:
            result = upgrade.result(timeout=max(0.0, deadline - time.time()))
        except (OSError, subprocess.SubprocessError) as exc:  # budget, no pixi
            report.unchecked.append(f"pixi upgrade ({_reason(exc)})")
        else:
            if result.returncode != 0:
                excerpt = _solve_excerpt(result.stderr)
                report.solve_error = f"pixi upgrade failed to solve: {excerpt}"
            else:
                try:
                    upgrades = json.loads(result.stdout)
                    report.same_source = _same_source(upgrades, platform)
                except MALFORMED as exc:
                    report.unchecked.append(f"pixi upgrade ({_reason(exc)})")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    proposals = {f.name: f.candidate for f in report.same_source}
    for pkg, envs, other, candidate_source, candidate, wheel in found:
        if not _newer(candidate, pkg["version"], proposals.get(pkg["name"])):
            continue
        conda = pkg["kind"] == "conda"
        report.cross_source.append(
            Finding(
                name=pkg["name"],
                pypi_name=other if conda else None,
                source=pkg["source"].rstrip("/").rsplit("/", 1)[-1]
                if conda
                else "pypi",
                locked=pkg["version"],
                candidate=candidate,
                candidate_source=candidate_source,
                wheel=wheel,
                spec=_spec(pkg),
                envs=envs,
            )
        )
    report.cross_source.sort(key=lambda f: f.name)
    return report, reusable


def _parse_report(cached: dict) -> DepReport | None:
    """The report a cache holds, however old, or None when it is malformed."""
    try:
        return DepReport(
            applicable=True,
            platform=cached["platform"],
            same_source=[Finding(**f) for f in cached["same_source"]],
            cross_source=[Finding(**f) for f in cached["cross_source"]],
            solve_error=cached["solve_error"],
            pixi_missing=False,
            unchecked=list(cached["unchecked"]),
            notes=list(cached["notes"]),
            from_cache=True,
        )
    except (KeyError, TypeError):
        return None


def _cached_report(cached: dict | None, stamp: dict, now: float) -> DepReport | None:
    """The cached report when fresh, else None (also for any malformed cache).

    A cache holding unchecked items is fresh for RETRY_SECONDS only: what
    the budget or a failure cut short is retried within the hour instead of
    staying unknown for 24 h.
    """
    if cached is None:
        return None
    try:
        lifetime = RETRY_SECONDS if cached["unchecked"] else CACHE_SECONDS
        fresh = 0 <= now - cached["checked_at"] < lifetime and all(
            cached[key] == value for key, value in stamp.items()
        )
    except (KeyError, TypeError):
        return None
    return _parse_report(cached) if fresh else None


def _acked(cached: dict | None) -> list[dict]:
    acked = (cached or {}).get("acked")
    if not isinstance(acked, list):
        return []
    return [
        a
        for a in acked
        if isinstance(a, dict) and {"name", "source", "version"} <= a.keys()
    ]


def _unacked(findings: list[Finding], acked: list[dict]) -> list[Finding]:
    """Findings newer than any acknowledged version of the same package."""
    ceiling = {(a["name"], a["source"]): a["version"] for a in acked}
    return [
        f
        for f in findings
        if (f.name, f.candidate_source) not in ceiling
        or _newer(f.candidate, ceiling[(f.name, f.candidate_source)])
    ]


def _cache_path(root: Path) -> Path:
    return root / ".pixi" / "agent-drift" / "deps.json"


def _lock_path(root: Path) -> Path:
    return _cache_path(root).with_name("refresh.lock")


def _stamp(root: Path, manifest: Path) -> dict:
    return {
        "lock_sha256": _sha256(root / "pixi.lock"),
        "manifest_sha256": _sha256(manifest),
    }


def _apply_acks(report: DepReport, acked: list[dict]) -> DepReport:
    report.same_source = _unacked(report.same_source, acked)
    report.cross_source = _unacked(report.cross_source, acked)
    return report


def _fresh(data: dict | None, stamp: dict, now: float) -> DepReport | None:
    report = _cached_report(data, stamp, now)
    return None if report is None else _apply_acks(report, _acked(data))


def cached(root: Path, *, now: float) -> DepReport | None:
    """The fresh cached report, or None when a refresh is due.

    Never computes: the SessionStart hook cannot wait on the network or on
    ``pixi list`` (~21 s per env on one project), so it reads this (through
    cache_view) and starts a detached ``--refresh`` when it is None.
    ``preflight --offline`` reads it for the same reason.
    """
    manifest = _manifest(root)
    if manifest is None:
        return _blank(False, "")
    return _fresh(_read_json(_cache_path(root)), _stamp(root, manifest), now)


def last_known(root: Path) -> tuple[DepReport, float] | None:
    """The cached report however stale, and when it was checked; None when
    there is no readable cache.

    For a reader that must not compute but should not go blank either: the
    hook while its refresh runs, and preflight while another does.
    """
    data = _read_json(_cache_path(root))
    report = None if data is None else _parse_report(data)
    checked_at = (data or {}).get("checked_at")
    if report is None or not isinstance(checked_at, int | float):
        return None
    return _apply_acks(report, _acked(data)), checked_at


def as_of(checked_at: float) -> str:
    """The label for a result read from the cache, by local date."""
    return time.strftime("as of %Y-%m-%d", time.localtime(checked_at))


def refresh_running(
    root: Path, *, now: float, pid_alive: Callable[[int], bool]
) -> bool:
    return lock_holder(_lock_path(root), now=now, pid_alive=pid_alive) is not None


@dataclass
class CacheView:
    """What a reader that must not wait on a refresh can show.

    One decision for the SessionStart hook and preflight: each branched
    over the cache and the lock itself, and they drifted, the hook saying
    "refresh started" while a refresh was already running.
    """

    report: DepReport | None  # fresh, else the last known, else None
    checked_at: float | None  # set for a last-known report only
    state: str  # "fresh", "running" (a refresh holds the lock) or "due"

    @property
    def refresh(self) -> str:
        """The refresh this result waits on. For "due" the caller starts
        one (the hook) or computes instead (preflight)."""
        return "refresh in progress" if self.state == "running" else "refresh started"

    @property
    def label(self) -> str:
        """The suffix for a stale report's summary; empty when fresh."""
        if self.state == "fresh" or self.checked_at is None:
            return ""
        return f" ({as_of(self.checked_at)}; {self.refresh})"


def cache_view(
    root: Path, *, now: float, pid_alive: Callable[[int], bool]
) -> CacheView:
    report = cached(root, now=now)
    if report is not None:
        return CacheView(report, None, "fresh")
    running = refresh_running(root, now=now, pid_alive=pid_alive)
    known = last_known(root) or (None, None)
    return CacheView(*known, "running" if running else "due")


def check(
    root: Path,
    *,
    fetch: Fetch,
    run: Run,
    now: float,
    deadline: float,
    refresh: bool,
) -> DepReport:
    """Report updates for the pixi project at root.

    ``now`` is the epoch time used for cache age; ``deadline`` is an
    absolute ``time.time()`` value bounding every subprocess and request.
    """
    manifest = _manifest(root)
    if manifest is None:
        return _blank(False, "")
    cache_path = _cache_path(root)
    previous = _read_json(cache_path)
    stamp = _stamp(root, manifest)
    if not refresh and (report := _fresh(previous, stamp, now)) is not None:
        return report
    acked = _acked(previous)
    same_lock = previous is not None and all(
        previous.get(key) == value for key, value in stamp.items()
    )
    locked = previous.get("locked") if same_lock else None
    report, locked = _compute(
        root,
        fetch,
        run,
        now,
        deadline,
        locked if _valid_listing(locked) else None,
    )
    # No platform means pixi never answered; caching that would hide a
    # later fix to PATH for a day.
    if report.platform:
        record = dataclasses.asdict(report)
        del record["from_cache"]
        _write_json(
            cache_path,
            {
                "checked_at": now,
                **stamp,
                **record,
                "locked": locked,
                "acked": acked,
            },
        )
    return _apply_acks(report, acked)


def ack(root: Path, report: DepReport) -> None:
    """Acknowledge every finding in report, keeping earlier acknowledgements."""
    cache_path = _cache_path(root)
    cached = _read_json(cache_path) or {}
    acked = {(a["name"], a["source"]): a for a in _acked(cached)}
    for f in report.same_source + report.cross_source:
        acked[(f.name, f.candidate_source)] = {
            "name": f.name,
            "source": f.candidate_source,
            "version": f.candidate,
        }
    _write_json(cache_path, {**cached, "acked": list(acked.values())})


def render(report: DepReport, root: Path) -> tuple[str, list[str]]:
    """A summary line and the detail lines under it, for the project at root.

    The ack hint names the running interpreter, because bare `python` is
    the Microsoft Store stub on Windows, and the project, because the CLI
    defaults to cwd, which the reader of a hook's context need not share.
    """
    if not report.applicable:
        return "dependency updates: not a pixi project", []
    if report.pixi_missing:
        return "dependency updates: pixi not found on PATH", []
    parts = []
    if report.solve_error:
        parts.append("pixi upgrade failed")
    else:
        parts.append(f"{len(report.same_source)} same-source")
    parts.append(f"{len(report.cross_source)} cross-source")
    if report.unchecked:
        parts.append(f"{len(report.unchecked)} unchecked")
    if report.notes:
        parts.append("degraded")
    where = f" ({report.platform})" if report.platform else ""
    summary = f"dependency updates{where}: " + (
        "up to date" if is_clean(report) else ", ".join(parts)
    )
    lines = [report.solve_error] if report.solve_error else []
    for f in [] if report.solve_error else report.same_source:
        label = "env" if len(f.envs) == 1 else "envs"
        lines.append(
            f"{f.name}: {f.locked} -> {f.candidate} "
            f"({f.source}, {label} {', '.join(f.envs)}; pixi upgrade)"
        )
    for f in report.cross_source:
        alias = f" -> {f.pypi_name}" if f.pypi_name and f.pypi_name != f.name else ""
        spec = f', spec "{f.spec}"' if f.spec else ""
        other = "PyPI" if f.candidate_source == "pypi" else f.candidate_source
        wheel = f" ({f.wheel})" if f.wheel else ""
        lines.append(
            f"{f.name}{alias}: locked {f.locked} ({f.source}{spec}); "
            f"{other} has {f.candidate}{wheel} -- source switch (manifest change)"
        )
    if report.unchecked:
        lines.append("unchecked: " + ", ".join(report.unchecked))
    lines.extend(report.notes)
    if report.same_source or report.cross_source:
        lines.append(f"cross-source checked for {report.platform} only")
        lines.append(
            "Ask the user whether to update before other work (default: update). "
            f'If they decline: "{sys.executable}" "{Path(__file__).resolve()}" '
            f'"{root}" --ack'
        )
    # Collapse whitespace so that foreign text (a spec, a solver message)
    # can never start a line of its own in the hook's session context.
    return summary, [" ".join(line.split()) for line in lines]


def live_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "dep_updates"})
    with urllib.request.urlopen(request, timeout=REQUEST_SECONDS) as response:
        return response.read()


# Every pixi process the live runner has started and not yet reaped, so an
# interrupted refresh can kill its own children instead of orphaning them.
_children: set[subprocess.Popen] = set()


def live_run(root: Path) -> Run:
    """The real ``run``: pixi in ``root``, killed at its timeout.

    Popen rather than subprocess.run so that each child is registered in
    ``_children`` while it runs. ``CREATE_NO_WINDOW`` because the detached
    refresh has no console, and Windows gives a console child of such a
    process a visible window of its own.
    """

    def run(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
        # pixi writes UTF-8 whatever the console code page is.
        with subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as proc:
            _children.add(proc)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                raise
            finally:
                _children.discard(proc)
        return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)

    return run


def _lock_holder(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lock_holder(
    path: Path, *, now: float, pid_alive: Callable[[int], bool]
) -> int | None:
    """The pid of a live refresh holding the lock at path, else None.

    A lock whose pid is dead or unreadable, or which is older than
    LOCK_STALE_SECONDS, is stale: a refresh killed outright never releases
    it, and a pid alone cannot prove the holder is still the refresh.
    """
    try:
        age = now - path.stat().st_mtime
    except OSError:
        return None
    holder = _lock_holder(path)
    if holder is None or age > LOCK_STALE_SECONDS or not pid_alive(holder):
        return None
    return holder


def acquire_lock(
    path: Path, *, pid: int, now: float, pid_alive: Callable[[int], bool]
) -> int | None:
    """Take the refresh lock for ``pid``, or return the live holder's pid.

    The SessionStart hook starts a refresh whenever the cache is stale, so
    two sessions opened together would otherwise run two ~25 s refreshes
    of the same project. A stale lock (see lock_holder) is taken over. Two
    takers racing for one stale lock can both win; both write the cache
    atomically, so that costs a duplicate refresh, never a torn file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(5):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = lock_holder(path, now=now, pid_alive=pid_alive)
            if holder is not None:
                return holder
            # Windows refuses to unlink a file a peer still has open
            # mid-write; the next attempt then reads the peer's pid.
            try:
                path.unlink()
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(str(pid))
        return None
    raise OSError(f"could not take the refresh lock {path}")


def release_lock(path: Path, *, pid: int) -> None:
    """Remove the lock only if ``pid`` still holds it, never a successor's."""
    if _lock_holder(path) == pid:
        path.unlink(missing_ok=True)


def _exit_on_signal(signum, _frame):
    # SystemExit unwinds main's finally, which kills the pixi children.
    raise SystemExit(128 + signum)


def _report(root: Path, args) -> int:
    start = time.time()
    report = check(
        root,
        fetch=live_fetch,
        run=live_run(root),
        now=start,
        deadline=start + CLI_BUDGET_SECONDS,
        refresh=args.refresh,
    )
    if args.ack:
        ack(root, report)
        count = len(report.same_source) + len(report.cross_source)
        print(f"acknowledged {count} finding(s)")
    elif args.json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
    else:
        summary, lines = render(report, root)
        print(summary)
        for line in lines:
            print(f"  {line}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", nargs="?", default=".")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore the cache; refuses while another refresh holds the lock",
    )
    parser.add_argument("--ack", action="store_true", help="acknowledge findings")
    parser.add_argument("--json", action="store_true", help="print the raw report")
    args = parser.parse_args(argv)
    root = Path(args.project).resolve()
    if not args.refresh or _manifest(root) is None:
        return _report(root, args)

    lock, pid = _lock_path(root), os.getpid()
    holder = acquire_lock(
        lock, pid=pid, now=time.time(), pid_alive=platform_paths.pid_alive
    )
    if holder is not None:
        print(f"refresh already running (pid {holder})")
        return 0
    trapped = [
        getattr(signal, name)
        for name in ("SIGTERM", "SIGBREAK")
        if hasattr(signal, name)
    ]
    previous = {signum: signal.signal(signum, _exit_on_signal) for signum in trapped}
    try:
        return _report(root, args)
    finally:
        for proc in list(_children):
            proc.kill()
        release_lock(lock, pid=pid)
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
