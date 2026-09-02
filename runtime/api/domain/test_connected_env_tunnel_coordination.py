"""Machine-wide coordination of the shared local SSH forward."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess

import pytest

from yoke_core.domain import connected_env_readiness_connector as cer_c
from yoke_core.domain import connected_env_tunnel_coordination as coordination
from yoke_core.domain import machine_config

PORT = 6547


@pytest.fixture(autouse=True)
def machine_home(tmp_path, monkeypatch):
    """Keep coordination state out of the operator's real machine home."""
    monkeypatch.setenv(machine_config.HOME_ENV, str(tmp_path / "machine-home"))
    return tmp_path


def _lock_path():
    return coordination.coordination_dir(PORT) / coordination.LIFECYCLE_LOCK_NAME


def _dead_pid() -> int:
    """A pid that has certainly exited."""
    finished = subprocess.Popen(["true"])
    finished.wait()
    return finished.pid


def test_lock_refuses_while_another_holder_has_it_and_names_them():
    path = _lock_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A second descriptor is a second open file description, so this conflicts
    # exactly as another process's would.
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        with pytest.raises(cer_c.ConnectedEnvUnavailable) as excinfo:
            with coordination.lifecycle_lock(PORT, timeout=0.2):
                pytest.fail("entered the lock while another holder had it")
    finally:
        os.close(descriptor)

    message = str(excinfo.value)
    assert "still replacing the connected-env tunnel" in message
    assert f"127.0.0.1:{PORT}" in message


def test_lock_is_available_again_after_the_holder_leaves():
    with coordination.lifecycle_lock(PORT, timeout=1.0):
        pass
    with coordination.lifecycle_lock(PORT, timeout=1.0):
        pass  # a released lock is takeable; no timeout, no stale-file sweep


def test_lock_records_the_holder_for_a_waiter_to_name():
    with coordination.lifecycle_lock(PORT, timeout=1.0):
        payload = json.loads(_lock_path().read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()


def test_use_lease_is_visible_while_held_and_gone_afterwards():
    with coordination.use_lease(PORT, "fleet migration rehearsal of prod"):
        held = coordination.active_leases(PORT)
        assert [lease.pid for lease in held] == [os.getpid()]
        assert "fleet migration rehearsal of prod" in held[0].line
    assert coordination.active_leases(PORT) == []


def test_use_lease_can_be_excluded_for_its_own_holder():
    with coordination.use_lease(PORT, "this process's own copy"):
        assert coordination.active_leases(PORT, exclude_pid=os.getpid()) == []


def test_a_lease_whose_holder_is_gone_is_dropped():
    directory = coordination.coordination_dir(PORT) / coordination.LEASE_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    pid = _dead_pid()
    stale = directory / f"{pid}.json"
    stale.write_text(
        json.dumps({"pid": pid, "reason": "abandoned copy", "started_at": 0.0}),
        encoding="utf-8",
    )

    assert coordination.active_leases(PORT) == []
    assert not stale.exists()  # a lease outlives nothing but its holder


def test_an_unreadable_lease_file_is_dropped_rather_than_obeyed():
    directory = coordination.coordination_dir(PORT) / coordination.LEASE_DIR_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    (directory / "garbage.json").write_text("not json", encoding="utf-8")

    assert coordination.active_leases(PORT) == []


def test_lease_for_active_tunnel_is_a_noop_without_a_managed_forward(monkeypatch):
    monkeypatch.setattr(
        coordination,
        "detect",
        lambda: cer_c.Detection(cer_c.CONNECTOR_UNMANAGED, None, None, None),
    )
    with coordination.use_lease_for_active_tunnel("fleet rehearsal"):
        assert coordination.active_leases(PORT) == []


def test_lease_for_active_tunnel_leases_the_detected_port(monkeypatch):
    monkeypatch.setattr(
        coordination,
        "detect",
        lambda: cer_c.Detection(
            cer_c.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            "prod-db-admin",
            "host=127.0.0.1 port=6547 dbname=test",
            None,
            local_host="127.0.0.1",
            local_port=PORT,
        ),
    )
    with coordination.use_lease_for_active_tunnel("fleet rehearsal"):
        assert [lease.pid for lease in coordination.active_leases(PORT)] == [os.getpid()]
