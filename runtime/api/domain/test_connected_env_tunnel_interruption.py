"""An interrupted fleet copy must not leave tunnel recovery behind a stale lease."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from yoke_core.domain import connected_env_readiness_connector as connector
from yoke_core.domain import connected_env_tunnel_coordination as coordination
from yoke_core.domain import connected_env_tunnel_lifecycle as lifecycle
from yoke_core.domain import machine_config
from yoke_contracts.platform_process import ancestors, spawn_group, stop_group

pytestmark = pytest.mark.windows


@pytest.mark.parametrize("launcher", [False, True])
def test_reaped_preflight_releases_replacement_guard(tmp_path, monkeypatch, launcher):
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path))
    port = 6547
    spec = connector.TunnelSpec(
        local_host="127.0.0.1",
        local_port=port,
        bastion="test@example.invalid",
        identity_file="/tmp/key",
        remote_host="db.example.invalid",
        remote_port=5432,
    )
    script = (
        "from yoke_core.domain.connected_env_tunnel_coordination import use_lease\n"
        "import os,time\n"
        f"with use_lease({port}, 'fleet rehearsal'):\n"
        "    print('copying', os.getpid(), flush=True)\n"
        "    time.sleep(60)\n"
    )
    if launcher:
        script = (
            "import subprocess,sys; "
            f"child=subprocess.Popen([sys.executable, '-c', {script!r}]); "
            "child.wait()"
        )
    group = spawn_group(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    )
    child = group.process
    assert child is not None
    try:
        assert child.stdout is not None
        state, holder_text = child.stdout.readline().split()
        assert state == "copying"
        holder_pid = int(holder_text)
        assert holder_pid == group.pid or group.pid in {
            parent.pid for parent in ancestors(holder_pid)
        }
        lease_dir = coordination.coordination_dir(port) / coordination.LEASE_DIR_NAME
        lease_path = next(lease_dir.glob("*.json"))
        assert lease_path.exists()
        monkeypatch.setattr(lifecycle, "LEASE_WAIT_SECONDS", 0.0)
        with pytest.raises(connector.ConnectedEnvUnavailable) as refusal:
            lifecycle.replace_forward(spec, probe=lambda: False)
        assert f"pid={holder_pid}" in str(refusal.value)
        assert "Wait for that operation to finish, or stop it and retry" in str(
            refusal.value
        )

        stop_group(group, timeout=2.0)
        assert lease_path.exists()  # SIGTERM bypassed the child's finally block.
        monkeypatch.setattr(coordination, "pid_alive", lambda _pid: True)
        started = []
        monkeypatch.setattr(lifecycle, "_find_tunnel_pids", lambda _spec: [])
        monkeypatch.setattr(lifecycle, "_port_blocker_detail", lambda _spec: "")
        monkeypatch.setattr(
            lifecycle, "_start_tunnel", lambda _spec: started.append(_spec)
        )
        assert (
            lifecycle.replace_forward(spec, probe=lambda: False)
            == connector.ACTION_RESTARTED
        )
        assert started == [spec]
        assert not lease_path.exists()
    finally:
        stop_group(group, timeout=2.0)
