from __future__ import annotations

import subprocess

import capture_codex_exec


def fake_run(*args, stdout=b"", stderr=b"", returncode=0, **kwargs):
    fake_run.call = (args, kwargs)
    return subprocess.CompletedProcess(args[0], returncode, stdout, stderr)


def test_capture_preserves_stdout_and_child_status(tmp_path, capsys):
    code = capture_codex_exec.main(
        ["--root", str(tmp_path), "--", "test"],
        run=lambda *args, **kwargs: fake_run(
            *args,
            stdout=b'{"type":"item.completed"}\n',
            stderr=b"warning\n",
            returncode=7,
            **kwargs,
        ),
    )
    files = list(
        (tmp_path / ".agents" / "analytics" / "codex-exec" / "v1").glob("*.jsonl")
    )
    assert code == 7
    assert fake_run.call == (
        (["codex", "exec", "--json", "test"],),
        {"capture_output": True},
    )
    assert files[0].read_bytes() == b'{"type":"item.completed"}\n'
    assert "warning" in capsys.readouterr().err


def test_capture_requires_forwarded_arguments(tmp_path):
    assert capture_codex_exec.main(["--root", str(tmp_path)], run=fake_run) != 0
    assert not list((tmp_path / ".agents").rglob("*.jsonl"))


def test_capture_excludes_stderr_and_prints_path(tmp_path, capsys):
    capture_codex_exec.main(
        ["--root", str(tmp_path), "--", "prompt"],
        run=lambda *args, **kwargs: fake_run(
            *args, stdout=b"out\n", stderr=b"err\n", **kwargs
        ),
    )
    output = capsys.readouterr()
    assert output.err == "err\n"
    path = output.out.strip()
    assert path.endswith(".jsonl")
    assert (
        "err"
        not in (
            tmp_path
            / ".agents"
            / "analytics"
            / "codex-exec"
            / "v1"
            / path.split("\\")[-1]
        ).read_text()
    )


def test_missing_executable_returns_nonzero_without_capture(tmp_path):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    assert (
        capture_codex_exec.main(["--root", str(tmp_path), "--", "prompt"], run=missing)
        != 0
    )
    assert not list((tmp_path / ".agents").rglob("*.jsonl"))


def test_capture_root(tmp_path):
    assert (
        capture_codex_exec.capture_root(tmp_path)
        == tmp_path / ".agents" / "analytics" / "codex-exec" / "v1"
    )
