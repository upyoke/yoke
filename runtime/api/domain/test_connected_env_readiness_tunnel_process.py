"""Process-discovery and replacement-policy tests for the local SSH forward.

These stay separate from ``test_connected_env_readiness`` so the main
readiness test file remains under the authored-line cap.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_readiness_tunnel as tunnel
from yoke_core.domain import connected_env_tunnel_coordination as coordination
from yoke_core.domain import connected_env_tunnel_lifecycle as lifecycle
from yoke_core.domain import machine_config


def _spec() -> cer.TunnelSpec:
    return cer.TunnelSpec(
        local_host="127.0.0.1",
        local_port=6547,
        bastion="ubuntu@52.20.177.138",
        identity_file="/keys/yoke.pem",
        remote_host="aurora.example.internal",
        remote_port=5432,
    )


@pytest.fixture
def machine_home(tmp_path, monkeypatch):
    """Keep coordination state (lock, leases) out of the operator's home."""
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    return tmp_path


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def _write_lease(port: int, pid: int, reason: str) -> None:
    directory = coordination.coordination_dir(port) / coordination.LEASE_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    (directory / f"{pid}.json").write_text(
        json.dumps({"pid": pid, "reason": reason, "started_at": 0.0}),
        encoding="utf-8",
    )


def test_find_tunnel_pids_uses_dashdash_and_lsof_fallback(monkeypatch):
    spec = _spec()
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        del kwargs
        calls.append(list(args))
        if args[0] == "pgrep":
            return _completed("")
        if args[0] == "lsof":
            return _completed("123\n")
        if args[0] == "ps":
            return _completed(f"ssh -N -f -L {spec.forward_spec} {spec.bastion}\n")
        raise AssertionError(args)

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)

    assert lifecycle._find_tunnel_pids(spec) == [123]
    assert calls[0] == ["pgrep", "-f", "--", f"-L {spec.forward_spec}"]


def test_find_tunnel_pids_raises_on_pgrep_usage_failure(monkeypatch):
    spec = _spec()

    def fake_run(args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="pgrep: illegal option -- L\n",
        )

    monkeypatch.setattr(lifecycle.subprocess, "run", fake_run)

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        lifecycle._find_tunnel_pids(spec)

    msg = str(excinfo.value)
    assert "could not enumerate tunnel pids" in msg
    assert "pgrep rc=2" in msg


def test_transient_probe_failure_recovers_before_restart(machine_home, monkeypatch):
    spec = _spec()
    results = iter(["down (test)", "down (test)", None])
    replacements: list[object] = []
    sleeps: list[float] = []

    monkeypatch.setattr(
        tunnel,
        "detect",
        lambda: tunnel.Detection(
            cer.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            "cloud-test",
            "host=127.0.0.1 port=6547 dbname=test",
            spec,
            local_host="127.0.0.1",
            local_port=6547,
        ),
    )
    monkeypatch.setattr(tunnel, "_probe_failure", lambda dsn: next(results))
    monkeypatch.setattr(
        tunnel,
        "_replace_forward",
        lambda spec, dsn: replacements.append(spec),
    )
    monkeypatch.setattr(
        coordination,
        "lifecycle_lock",
        lambda _port: pytest.fail("a recovered probe cannot take the lock"),
    )
    monkeypatch.setattr(tunnel.time, "sleep", lambda delay: sleeps.append(delay))

    result = tunnel.evaluate(allow_restart=True)

    assert result.ok
    assert result.action == cer_c.ACTION_PROBE_OK
    assert "recovered before restart" in result.message
    assert replacements == []
    assert sleeps


def test_probe_window_tolerates_a_forward_slow_under_load(monkeypatch):
    """One slow answer under a bulk transfer is not a verdict."""
    results = iter(["down (test)"] * (cer_c.PROBE_CONFIRM_ATTEMPTS - 1) + [None])
    monkeypatch.setattr(tunnel, "_probe_failure", lambda dsn: next(results))
    monkeypatch.setattr(tunnel.time, "sleep", lambda delay: None)

    assert tunnel._probe_retry("host=127.0.0.1 port=6547 dbname=test") is None
    # The tolerance has to be measured in seconds on both axes: a connect that
    # queues behind a multi-minute dump needs the longer timeout, and the
    # window has to span more than a moment before calling the forward dead.
    assert cer_c.PROBE_TIMEOUT_SECONDS >= 15
    window = (cer_c.PROBE_CONFIRM_ATTEMPTS - 1) * cer_c.PROBE_CONFIRM_DELAY_SECONDS
    assert window >= 5


def test_replace_forward_fails_loudly_on_foreign_port_owner(machine_home, monkeypatch):
    spec = _spec()
    monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [])
    monkeypatch.setattr(lifecycle, "_terminate_pids", lambda pids: None)
    monkeypatch.setattr(lifecycle, "_listening_pids", lambda port: [222])
    monkeypatch.setattr(
        lifecycle, "_process_command", lambda pid: "python3 local-dev-server.py"
    )
    monkeypatch.setattr(
        lifecycle, "_start_tunnel", lambda _spec: pytest.fail("should not start")
    )

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        lifecycle.replace_forward(spec, probe=lambda: False)

    msg = str(excinfo.value)
    assert "local port is occupied" in msg
    assert "pid=222" in msg
    assert "local-dev-server.py" in msg


def test_replace_forward_terminates_dead_forward_then_starts(machine_home, monkeypatch):
    spec = _spec()
    calls: list[object] = []
    monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [123])
    monkeypatch.setattr(
        lifecycle, "_terminate_pids", lambda pids: calls.append(("term", tuple(pids)))
    )
    monkeypatch.setattr(lifecycle, "_port_blocker_detail", lambda _spec: "")
    monkeypatch.setattr(
        lifecycle, "_start_tunnel", lambda _spec: calls.append(("start", _spec))
    )

    action = lifecycle.replace_forward(spec, probe=lambda: False)

    assert action == cer_c.ACTION_RESTARTED
    assert calls == [("term", (123,)), ("start", spec)]


def test_replace_forward_adopts_a_forward_that_answers(machine_home, monkeypatch):
    """A matching forward that answers is the working forward: use it."""
    spec = _spec()
    monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [123])
    monkeypatch.setattr(
        lifecycle,
        "_terminate_pids",
        lambda pids: pytest.fail("must not terminate"),
    )
    monkeypatch.setattr(
        lifecycle, "_start_tunnel", lambda _spec: pytest.fail("must not start")
    )

    action = lifecycle.replace_forward(spec, probe=lambda: True)

    assert action == cer_c.ACTION_ADOPTED


def test_replace_forward_adopts_a_forward_bound_after_termination(
    machine_home, monkeypatch
):
    """The bind race: a neighbour claims the port while we are terminating."""
    spec = _spec()
    answers = iter([False, True])
    monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [123])
    monkeypatch.setattr(lifecycle, "_terminate_pids", lambda pids: None)
    monkeypatch.setattr(
        lifecycle, "_start_tunnel", lambda _spec: pytest.fail("must not start")
    )

    action = lifecycle.replace_forward(spec, probe=lambda: next(answers))

    assert action == cer_c.ACTION_ADOPTED


def test_replace_forward_waits_out_a_lease_and_adopts_the_forward(
    machine_home, monkeypatch
):
    """A forward under a bulk transfer is usually slow, not dead."""
    spec = _spec()
    _write_lease(spec.local_port, os.getppid(), "fleet migration rehearsal of prod")
    answers = iter([False, True])
    monkeypatch.setattr(lifecycle.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        lifecycle,
        "_terminate_pids",
        lambda pids: pytest.fail("must not terminate"),
    )

    action = lifecycle.replace_forward(spec, probe=lambda: next(answers))

    assert action == cer_c.ACTION_ADOPTED


def test_replace_forward_refuses_while_another_process_holds_a_lease(
    machine_home, monkeypatch
):
    """The observed outage: a restart killed a forward mid bulk transfer."""
    spec = _spec()
    _write_lease(spec.local_port, os.getppid(), "fleet migration rehearsal of prod")
    monkeypatch.setattr(lifecycle, "LEASE_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(
        lifecycle,
        "_find_tunnel_pids",
        lambda _spec: pytest.fail("must not enumerate"),
    )
    monkeypatch.setattr(
        lifecycle,
        "_terminate_pids",
        lambda pids: pytest.fail("must not terminate"),
    )

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        lifecycle.replace_forward(spec, probe=lambda: False)

    msg = str(excinfo.value)
    assert "carrying another process's long operation" in msg
    assert f"pid={os.getppid()}" in msg
    assert "fleet migration rehearsal of prod" in msg


def test_replace_forward_ignores_this_process_own_lease(machine_home, monkeypatch):
    """A process may heal the forward it is itself using."""
    spec = _spec()
    _write_lease(spec.local_port, os.getpid(), "this session's own copy")
    started: list[object] = []
    monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [])
    monkeypatch.setattr(lifecycle, "_terminate_pids", lambda pids: None)
    monkeypatch.setattr(lifecycle, "_port_blocker_detail", lambda _spec: "")
    monkeypatch.setattr(lifecycle, "_start_tunnel", lambda _spec: started.append(_spec))

    assert (
        lifecycle.replace_forward(spec, probe=lambda: False) == cer_c.ACTION_RESTARTED
    )
    assert started == [spec]


def test_build_ssh_argv_matches_operator_shape():
    spec = cer.TunnelSpec(
        local_host="127.0.0.1",
        local_port=6547,
        bastion="ubuntu@1.2.3.4",
        identity_file="/keys/k.pem",
        remote_host="aurora.x",
        remote_port=5432,
    )
    argv = lifecycle._build_ssh_argv(spec)

    assert argv[0] == "ssh"
    assert argv[1:3] == ["-i", "/keys/k.pem"]
    assert "-N" in argv and "-f" in argv
    assert argv[argv.index("-L") + 1] == "6547:aurora.x:5432"
    assert argv[-1] == "ubuntu@1.2.3.4"
    joined = " ".join(argv)
    assert "BatchMode=yes" in joined
    assert "ExitOnForwardFailure=yes" in joined
    # Keepalives must outlast a bulk transfer: ssh's own window is not the
    # liveness authority, and a short one killed a forward mid-copy.
    keepalive_window = (
        cer_c.SSH_KEEPALIVE_INTERVAL_SECONDS * cer_c.SSH_KEEPALIVE_COUNT_MAX
    )
    assert keepalive_window >= 600
    assert f"ServerAliveInterval={cer_c.SSH_KEEPALIVE_INTERVAL_SECONDS}" in joined
    assert f"ServerAliveCountMax={cer_c.SSH_KEEPALIVE_COUNT_MAX}" in joined
