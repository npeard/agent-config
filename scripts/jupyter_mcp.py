#!/usr/bin/env python
"""Start JupyterLab detached and print the line that registers its MCP server.

Automates the notebooks skill's manual steps: if nothing listens on the port,
launch JupyterLab from this interpreter's environment (run it through the
project's task runner so the kernel is the project's), wait for its HTTP
status endpoint, then print the `claude mcp add` command. Nothing is
registered here: the command is printed for the user or agent to run.

Usage:
    jupyter-mcp --port 8889 --token TOKEN --timeout 60 --root REPO
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

POLL_SECONDS = 1.0


def is_listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def lab_command(port: int, token: str, root: Path) -> list[str]:
    return [
        sys.executable,
        *("-m", "jupyterlab", "--no-browser"),
        f"--port={port}",
        f"--IdentityProvider.token={token}",
        f"--ServerApp.root_dir={root}",
    ]


def start_detached(argv: list[str]) -> None:
    """Launch `argv` so it outlives this process and opens no console window.

    A server that is a child of the agent session dies at every restart.
    """
    if sys.platform == "win32":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_NO_WINDOW
        )
        extra = {"creationflags": flags}
    else:
        extra = {"start_new_session": True}
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **extra,
    )


def wait_until_up(port: int, token: str, timeout: float) -> bool:
    """Poll /api/status until it answers 200. A bound port alone proves
    nothing: the socket opens before the server can serve."""
    request = urllib.request.Request(
        f"http://localhost:{port}/api/status",
        headers={"Authorization": f"token {token}"},
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(POLL_SECONDS)
    return False


def mcp_add_command(port: int, token: str) -> str:
    return (
        "claude mcp add jupyter --scope local "
        f"--env JUPYTER_URL=http://localhost:{port} --env JUPYTER_TOKEN={token} "
        "-- uvx jupyter-mcp-server@latest start --transport stdio"
    )


def main(argv: list[str] | None = None) -> int:
    # Escape what cp1252 stdout cannot encode; see check_ascii.main.
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument(
        "--timeout", type=float, required=True, help="seconds to wait for the server"
    )
    parser.add_argument("--root", type=Path, required=True, help="notebook root dir")
    args = parser.parse_args(argv)

    if is_listening(args.port):
        print(f"JupyterLab already listening on port {args.port}.")
    else:
        start_detached(lab_command(args.port, args.token, args.root.resolve()))
        if not wait_until_up(args.port, args.token, args.timeout):
            print(f"JupyterLab did not answer on port {args.port} in {args.timeout}s.")
            return 1
        print(f"JupyterLab started on port {args.port}.")
    print(
        "Register the MCP server (run `uvx jupyter-mcp-server@latest --help` once "
        "first: its first run downloads and times out):\n"
        f"  {mcp_add_command(args.port, args.token)}\n"
        "Adding a server may need a session restart before the "
        "mcp__jupyter__* tools load (unverified)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
