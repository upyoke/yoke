from __future__ import annotations

import io
from subprocess import CompletedProcess, TimeoutExpired

from yoke_core.domain.timeout_portable import run_command


def test_success_passthrough(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        assert timeout == 5
        return CompletedProcess(cmd, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr("yoke_core.domain.timeout_portable.subprocess.run", fake_run)
    out = io.StringIO()
    err = io.StringIO()
    assert run_command(["5", "echo", "hello"], out=out, err=err) == 0
    assert out.getvalue() == "hello\n"
    assert err.getvalue() == ""


def test_timeout_returns_124(monkeypatch):
    def fake_run(cmd, text, capture_output, timeout):
        raise TimeoutExpired(cmd, timeout, output="", stderr="")

    monkeypatch.setattr("yoke_core.domain.timeout_portable.subprocess.run", fake_run)
    assert run_command(["1", "sleep", "10"], out=io.StringIO(), err=io.StringIO()) == 124


def test_bad_timeout_returns_125():
    err = io.StringIO()
    assert run_command(["abc", "echo", "hi"], out=io.StringIO(), err=err) == 125
    assert "positive integer" in err.getvalue()
