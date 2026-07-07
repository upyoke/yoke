"""Process-discovery tests for connected-env tunnel restart.

These stay separate from ``test_connected_env_readiness`` so the main
readiness test file remains under the authored-line cap.
"""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain import connected_env_readiness as cer
from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_readiness_tunnel as tunnel


def _spec() -> cer.TunnelSpec:
    return cer.TunnelSpec(
        local_host="127.0.0.1",
        local_port=6547,
        bastion="ubuntu@52.20.177.138",
        identity_file="/keys/yoke.pem",
        remote_host="aurora.example.internal",
        remote_port=5432,
    )


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


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

    monkeypatch.setattr(tunnel.subprocess, "run", fake_run)

    assert tunnel._find_tunnel_pids(spec) == [123]
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

    monkeypatch.setattr(tunnel.subprocess, "run", fake_run)

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        tunnel._find_tunnel_pids(spec)

    msg = str(excinfo.value)
    assert "could not enumerate tunnel pids" in msg
    assert "pgrep rc=2" in msg


def test_transient_probe_failure_recovers_before_restart(monkeypatch):
    spec = _spec()
    results = iter([False, False, True])
    restarts: list[object] = []
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
    monkeypatch.setattr(tunnel, "_probe", lambda dsn: next(results))
    monkeypatch.setattr(tunnel, "_restart_tunnel", lambda spec: restarts.append(spec))
    monkeypatch.setattr(tunnel.time, "sleep", lambda delay: sleeps.append(delay))

    result = tunnel.evaluate(allow_restart=True)

    assert result.ok
    assert result.action == cer_c.ACTION_PROBE_OK
    assert "recovered before restart" in result.message
    assert restarts == []
    assert sleeps


def test_restart_tunnel_fails_loudly_on_foreign_port_owner(monkeypatch):
    spec = _spec()
    monkeypatch.setattr(tunnel, "_find_tunnel_pids", lambda _spec: [])
    monkeypatch.setattr(tunnel, "_terminate_pids", lambda pids: None)
    monkeypatch.setattr(tunnel, "_listening_pids", lambda port: [222])
    monkeypatch.setattr(tunnel, "_process_command", lambda pid: "python3 local-dev-server.py")
    monkeypatch.setattr(tunnel, "_start_tunnel", lambda _spec: pytest.fail("should not start"))

    with pytest.raises(cer.ConnectedEnvUnavailable) as excinfo:
        tunnel._restart_tunnel(spec)

    msg = str(excinfo.value)
    assert "local port is occupied" in msg
    assert "pid=222" in msg
    assert "local-dev-server.py" in msg


def test_restart_tunnel_terminates_matching_forward_then_starts(monkeypatch):
    spec = _spec()
    calls: list[object] = []
    monkeypatch.setattr(tunnel, "_find_tunnel_pids", lambda _spec: [123])
    monkeypatch.setattr(tunnel, "_terminate_pids", lambda pids: calls.append(("term", tuple(pids))))
    monkeypatch.setattr(tunnel, "_port_blocker_detail", lambda _spec: "")
    monkeypatch.setattr(tunnel, "_start_tunnel", lambda _spec: calls.append(("start", _spec)))

    tunnel._restart_tunnel(spec)

    assert calls == [("term", (123,)), ("start", spec)]
