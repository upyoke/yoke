"""Portable foreground SSH startup and process custody, without a live SSH host."""

from __future__ import annotations

import dataclasses
import socket
import sys
import time

import pytest

from yoke_core.domain import connected_env_readiness_connector as connector
from yoke_core.domain import connected_env_tunnel_lifecycle as lifecycle
from yoke_core.domain import ssh_forward_process as forward


def _spec(port=6547):
    return connector.TunnelSpec(
        local_host="127.0.0.1",
        local_port=port,
        bastion="database-host",
        identity_file="/keys/operator.pem",
        remote_host="database.internal",
        remote_port=5432,
    )


@pytest.fixture
def spawned(monkeypatch):
    handles = []
    real_spawn = forward.spawn_group

    def spawn(*args, **kwargs):
        handle = real_spawn(*args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(forward, "spawn_group", spawn)
    yield handles
    for handle in handles:
        forward.stop_group(handle, timeout=1.0)


def test_start_waits_for_listener_and_leaves_the_forward_running(monkeypatch, spawned):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    script = (
        "import socket,time; time.sleep(0.15); s=socket.socket(); "
        f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(30)"
    )
    monkeypatch.setattr(
        lifecycle, "_build_ssh_argv", lambda spec: [sys.executable, "-c", script]
    )
    monkeypatch.setattr(lifecycle, "TUNNEL_START_TIMEOUT_SECONDS", 3)
    started = time.monotonic()
    lifecycle._start_tunnel(_spec(port))
    assert time.monotonic() - started >= 0.1
    assert spawned[0].process.poll() is None


def test_nonzero_exit_refusal_carries_stderr(monkeypatch, spawned):
    script = "import sys,time; time.sleep(0.1); print('Permission denied (publickey).',file=sys.stderr); sys.exit(255)"
    monkeypatch.setattr(
        lifecycle, "_build_ssh_argv", lambda spec: [sys.executable, "-c", script]
    )
    with pytest.raises(
        connector.ConnectedEnvUnavailable, match="rc=255.*Permission denied"
    ):
        lifecycle._start_tunnel(_spec())
    assert spawned[0].process.returncode == 255


def test_non_listening_child_times_out_and_is_reaped(monkeypatch, spawned):
    monkeypatch.setattr(
        lifecycle,
        "_build_ssh_argv",
        lambda spec: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    monkeypatch.setattr(lifecycle, "TUNNEL_START_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(
        connector.ConnectedEnvUnavailable, match="timed out after 0.2s.*retry"
    ):
        lifecycle._start_tunnel(_spec())
    assert spawned[0].process.returncode is not None


def test_argv_uses_foreground_ssh_on_all_platforms():
    argv = lifecycle._build_ssh_argv(_spec())
    assert "-N" in argv and "-f" not in argv
    assert "-F" not in argv
    assert "StrictHostKeyChecking=accept-new" in argv


def test_argv_with_ssh_config_keeps_its_host_key_pin():
    argv = lifecycle._build_ssh_argv(
        dataclasses.replace(_spec(), ssh_config="operator-ssh.conf")
    )
    assert argv[:3] == ["ssh", "-F", "operator-ssh.conf"]
    assert not any(part.startswith("StrictHostKeyChecking") for part in argv)
    assert argv[-1] == "database-host"
