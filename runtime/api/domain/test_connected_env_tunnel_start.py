"""Tests for starting the backgrounded ssh forward against a fake ``ssh``.

A ProxyCommand/ProxyJump host leaves a proxy child holding ssh's inherited
stderr open for the tunnel's whole life; the start must still return as soon
as ssh itself has backgrounded and exited 0.
"""

from __future__ import annotations

import dataclasses
import os
import signal
import stat
import time
from pathlib import Path

import pytest

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_tunnel_lifecycle as lifecycle

_TIMEOUT_SECONDS = 3


def _spec() -> cer.TunnelSpec:
    return cer.TunnelSpec(
        local_host="127.0.0.1",
        local_port=6547,
        bastion="yoke-prod-box",
        identity_file="/keys/yoke.pem",
        remote_host="aurora.example.internal",
        remote_port=5432,
    )


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """Install a fake ``ssh`` on PATH; returns a writer for its body."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(lifecycle, "TUNNEL_START_TIMEOUT_SECONDS", _TIMEOUT_SECONDS)
    script = bin_dir / "ssh"

    def write(body: str) -> Path:
        script.write_text("#!/bin/sh\n" + body)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    return write


@pytest.fixture
def child_pid_file(tmp_path):
    """Kill whatever lingering child the fake ssh recorded."""
    pid_file = tmp_path / "child.pid"
    yield pid_file
    if pid_file.exists():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def test_start_returns_while_proxy_child_holds_stderr(fake_ssh, child_pid_file):
    # The child inherits stderr and outlives ssh, like a ProxyCommand does.
    fake_ssh(f"sleep 30 &\necho $! > '{child_pid_file}'\nexit 0\n")

    started = time.monotonic()
    lifecycle._start_tunnel(_spec())
    elapsed = time.monotonic() - started

    assert elapsed < _TIMEOUT_SECONDS
    assert child_pid_file.read_text().strip()


def test_nonzero_exit_refusal_carries_stderr(fake_ssh):
    fake_ssh("echo 'Permission denied (publickey).' >&2\nexit 255\n")

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        lifecycle._start_tunnel(_spec())

    message = str(excinfo.value)
    assert "rc=255" in message
    assert "Permission denied (publickey)." in message


def test_ssh_that_never_backgrounds_hits_named_timeout(fake_ssh, child_pid_file):
    fake_ssh(f"echo $$ > '{child_pid_file}'\nexec sleep 30\n")

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        lifecycle._start_tunnel(_spec())

    assert f"timed out after {_TIMEOUT_SECONDS}s" in str(excinfo.value)


def test_argv_without_ssh_config_reads_the_users_ssh_config():
    argv = lifecycle._build_ssh_argv(_spec())

    assert "-F" not in argv
    assert "StrictHostKeyChecking=accept-new" in argv


def test_argv_with_ssh_config_passes_it_and_keeps_its_host_key_pin():
    spec = dataclasses.replace(_spec(), ssh_config="/home/o/.yoke/ssh/config")

    argv = lifecycle._build_ssh_argv(spec)

    assert argv[:3] == ["ssh", "-F", "/home/o/.yoke/ssh/config"]
    assert not any(part.startswith("StrictHostKeyChecking") for part in argv)
    assert argv[-1] == "yoke-prod-box"
