"""Installation readiness and safe evaluator retirement."""

import subprocess
from unittest.mock import Mock

import pytest

from yoke_cli import hook_resident_client as client
from yoke_cli import hook_resident_lifecycle as lifecycle


def test_restart_warms_a_real_evaluator_and_replaces_same_version(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    paths = client.resident_paths()
    try:
        lifecycle.restart_resident()
        first = lifecycle._resident_processes(paths)
        assert len(first) == 1
        # Readiness is a real evaluation, not just a listening socket.
        result = client.evaluate_with_resident("PreToolUse", "{}", dry_run=True)
        assert result.exit_code == 0
        lifecycle.restart_resident()
        second = lifecycle._resident_processes(paths)
        assert len(second) == 1
        assert second != first
        assert lifecycle.process_start_time(first[0][0]) != first[0][1]
        lifecycle.stop_resident()
        assert lifecycle._resident_processes(paths) == []
        assert not paths.socket.exists()
    finally:
        lifecycle.stop_resident()


def test_missing_evaluator_is_a_successful_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    lifecycle.stop_resident()


def test_unsupported_transport_stops_cleanly_and_refuses_restart(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(client, "resident_transport_available", lambda: False)

    lifecycle.stop_resident()
    with pytest.raises(
        lifecycle.ResidentLifecycleError, match="YOKE_HOOK_RESIDENT_UNSUPPORTED"
    ):
        lifecycle.restart_resident()


def test_process_discovery_requires_exact_module_and_machine_socket(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    paths = client.resident_paths()
    listing = "\n".join(
        [
            f"101 python -m yoke_harness.hook_resident --socket {paths.socket} --lock-fd 3",
            "102 python -m yoke_harness.hook_resident --socket /other.sock --lock-fd 3",
            f"103 echo -m yoke_harness.hook_resident --socket {paths.socket} --lock-fd 3",
            f"104 python -m unrelated --socket {paths.socket}",
        ]
    )
    monkeypatch.setattr(
        lifecycle.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, listing, ""),
    )
    monkeypatch.setattr(lifecycle, "process_start_time", lambda pid: "start")
    monkeypatch.setattr(
        lifecycle,
        "process_command_name",
        lambda pid: "echo" if pid == 103 else "python3",
    )
    # ps output cannot certify the executable by argv text alone.
    assert lifecycle._resident_processes(paths) == [(101, "start")]


def test_stop_does_not_signal_reused_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [(123, "old")])
    monkeypatch.setattr(lifecycle, "process_start_time", lambda pid: "new")
    signal = Mock()
    monkeypatch.setattr(lifecycle.os, "kill", signal)
    lifecycle.stop_resident()
    signal.assert_not_called()


def test_unreleased_lock_refuses_instead_of_claiming_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [])
    monkeypatch.setattr(client, "_open_start_lock", lambda path: None)
    monkeypatch.setattr(lifecycle, "_STOP_SECONDS", 0.001)
    with pytest.raises(
        lifecycle.ResidentLifecycleError, match="YOKE_HOOK_RESIDENT_STOP_TIMEOUT"
    ):
        lifecycle.stop_resident()


def test_restart_accepts_a_resident_a_live_hook_relaunched(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [])
    # A live hook's new resident holds the start lock once the old one exits.
    monkeypatch.setattr(client, "_open_start_lock", lambda path: None)
    monkeypatch.setattr(lifecycle, "_STOP_SECONDS", 0.001)
    lifecycle.stop_resident(require_lock_release=False)


def test_nonzero_health_refuses_readiness(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "stop_resident", lambda paths, **_: None)
    monkeypatch.setattr(client, "_start_resident", lambda *_: None)
    monkeypatch.setattr(
        client,
        "_round_trip",
        lambda *_a, **_k: {"status": "ok", "stdout": "", "stderr": "", "exit_code": 1},
    )
    with pytest.raises(
        lifecycle.ResidentLifecycleError, match="YOKE_HOOK_RESIDENT_HEALTH_FAILED"
    ):
        lifecycle.restart_resident()


def test_start_timeout_names_log_and_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "stop_resident", lambda paths, **_: None)
    monkeypatch.setattr(client, "_start_resident", lambda *_: None)
    monkeypatch.setattr(lifecycle, "_START_SECONDS", 0)
    with pytest.raises(
        lifecycle.ResidentLifecycleError, match="YOKE_HOOK_RESIDENT_START_TIMEOUT"
    ) as failure:
        lifecycle.restart_resident()
    assert str(client.resident_paths().log) in str(failure.value)
    assert "yoke hook resident restart" in str(failure.value)


def test_cli_reports_unwritable_cache_without_retrying_path_creation(
    monkeypatch, capsys
):
    def fail():
        raise PermissionError("cache is not writable")

    monkeypatch.setattr(lifecycle, "restart_resident", fail)
    monkeypatch.setattr(client, "resident_paths", fail)
    assert lifecycle.resident_lifecycle(["restart"]) == 1
    assert "YOKE_HOOK_RESIDENT_LIFECYCLE_FAILED" in capsys.readouterr().out
