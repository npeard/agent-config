from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path


def capture_root(home: Path) -> Path:
    return home / ".agents" / "analytics" / "codex-exec" / "v1"


def main(
    argv: list[str],
    *,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> int:
    parser = argparse.ArgumentParser(
        description="Capture explicit codex exec JSONL output"
    )
    parser.add_argument("--root", type=Path, default=Path.home())
    parser.add_argument("forwarded", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = args.forwarded
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    if not forwarded:
        print("arguments after -- are required", file=sys.stderr)
        return 2

    try:
        result = run(["codex", "exec", "--json", *forwarded], capture_output=True)
    except FileNotFoundError:
        print("codex executable not found", file=sys.stderr)
        return 1

    sys.stderr.buffer.write(result.stderr)
    sys.stderr.buffer.flush()
    root = capture_root(args.root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{uuid.uuid4()}.jsonl"
    path.write_bytes(result.stdout)
    print(path)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
