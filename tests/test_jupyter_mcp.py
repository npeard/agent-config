"""Tests for scripts/jupyter_mcp.py; no test launches a real JupyterLab."""

from __future__ import annotations

import socket

import jupyter_mcp
import pytest


@pytest.fixture
def listener():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield sock.getsockname()[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_a_listening_port_is_detected(listener):
    assert jupyter_mcp.is_listening(listener)


def test_a_closed_port_is_not_listening():
    assert not jupyter_mcp.is_listening(free_port())


def test_the_printed_command_is_the_skills_line():
    assert jupyter_mcp.mcp_add_command(8889, "tok") == (
        "claude mcp add jupyter --scope local "
        "--env JUPYTER_URL=http://localhost:8889 --env JUPYTER_TOKEN=tok "
        "-- uvx jupyter-mcp-server@latest start --transport stdio"
    )


def test_jupyterlab_is_launched_with_the_skills_flags(tmp_path):
    argv = jupyter_mcp.lab_command(8889, "tok", tmp_path)
    assert argv[1:4] == ["-m", "jupyterlab", "--no-browser"]
    assert "--port=8889" in argv
    assert "--IdentityProvider.token=tok" in argv
    assert f"--ServerApp.root_dir={tmp_path}" in argv


def run(monkeypatch, capsys, *, listening, up):
    launched = []
    monkeypatch.setattr(jupyter_mcp, "is_listening", lambda port: listening)
    monkeypatch.setattr(
        jupyter_mcp, "start_detached", lambda argv: launched.append(argv)
    )
    monkeypatch.setattr(jupyter_mcp, "wait_until_up", lambda *a: up)
    argv = ["--port", "8889", "--token", "tok", "--timeout", "5", "--root", "."]
    code = jupyter_mcp.main(argv)
    return code, launched, capsys.readouterr().out


def test_an_already_listening_server_is_not_relaunched(monkeypatch, capsys):
    code, launched, out = run(monkeypatch, capsys, listening=True, up=True)
    assert code == 0 and launched == []
    assert "claude mcp add jupyter" in out and "restart" in out


def test_a_missing_server_is_started_then_the_command_is_printed(monkeypatch, capsys):
    code, launched, out = run(monkeypatch, capsys, listening=False, up=True)
    assert code == 0 and len(launched) == 1
    assert "claude mcp add jupyter" in out


def test_a_server_that_never_comes_up_fails_without_the_command(monkeypatch, capsys):
    code, _, out = run(monkeypatch, capsys, listening=False, up=False)
    assert code == 1
    assert "claude mcp add" not in out
