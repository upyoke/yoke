"""Installation readiness and safe evaluator retirement."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from yoke_contracts import platform_process
from yoke_cli import hook_resident_client as client
from yoke_cli import hook_resident_lifecycle as lifecycle
from yoke_cli import hook_resident_paths as resident_paths


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
        assert not platform_process.pid_alive(*first[0])
        lifecycle.stop_resident()
        assert lifecycle._resident_processes(paths) == []
        assert not paths.socket.exists()
    finally:
        lifecycle.stop_resident()


@pytest.mark.skipif(os.name == "nt", reason="POSIX socket path limit")
def test_long_tmpdir_still_binds_a_short_evaluator_socket(monkeypatch, tmp_path):
    long_home = tmp_path / ("nested-machine-home-" * 6)
    long_tmpdir = long_home / "tmp"
    long_tmpdir.mkdir(parents=True)
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: long_home)
    monkeypatch.setenv("TMPDIR", str(long_tmpdir))
    monkeypatch.setattr(tempfile, "tempdir", None)
    paths = client.resident_paths()
    assert len(os.fsencode(long_tmpdir / paths.socket.name)) > 100
    assert paths.socket.parent == Path("/tmp")
    try:
        lifecycle.restart_resident()
        assert paths.socket.is_socket()
        result = client.evaluate_with_resident("PreToolUse", "{}", dry_run=True)
        assert result.exit_code == 0
    finally:
        lifecycle.stop_resident()


@pytest.mark.skipif(os.name == "nt", reason="POSIX socket path limit")
def test_unbindable_socket_path_refuses_with_its_recovery(monkeypatch, tmp_path):
    long_home = tmp_path / ("nested-machine-home-" * 6)
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: long_home)
    monkeypatch.setattr(resident_paths, "shortest_temp_directory", lambda: None)

    with pytest.raises(
        lifecycle.ResidentLifecycleError,
        match="YOKE_HOOK_RESIDENT_SOCKET_PATH_TOO_LONG",
    ) as failure:
        lifecycle.restart_resident()
    assert "set TMPDIR to a short writable directory" in str(failure.value)
    with pytest.raises(client.ResidentUnavailable) as unavailable:
        client.evaluate_with_resident("PreToolUse", "{}", dry_run=True)
    assert unavailable.value.code == "YOKE_HOOK_RESIDENT_SOCKET_PATH_TOO_LONG"


def test_missing_evaluator_is_a_successful_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    lifecycle.stop_resident()


@pytest.mark.skipif(os.name == "nt", reason="Windows uses named pipes")
def test_unsupported_transport_stops_cleanly_and_refuses_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.delattr(client.socket, "AF_UNIX", raising=False)

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

    def process(pid, *argv):
        return SimpleNamespace(pid=pid, start_time=float(pid), cmdline=tuple(argv))

    listing = [
        process(
            101,
            "python3",
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(paths.socket),
            "--lock-fd",
            "3",
        ),
        process(
            102,
            "python3",
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            "/other.sock",
            "--lock-fd",
            "3",
        ),
        process(
            103,
            "echo",
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(paths.socket),
            "--lock-fd",
            "3",
        ),
        process(104, "python3", "-m", "unrelated", "--socket", str(paths.socket)),
        process(
            105,
            "C:\\Python\\python.exe",
            "-m",
            "yoke_harness.hook_resident",
            "--socket",
            str(paths.socket),
            "--lock-path",
            str(paths.lock),
        ),
    ]
    monkeypatch.setattr(platform_process, "process_command_lines", lambda: listing)
    assert lifecycle._resident_processes(paths) == [(101, 101.0), (105, 105.0)]


def test_stop_does_not_signal_reused_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [(123, 1.0)])
    monkeypatch.setattr(platform_process, "handle_from_pid", lambda *args: None)
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: False)
    stop = Mock()
    monkeypatch.setattr(platform_process, "stop_group", stop)
    lifecycle.stop_resident()
    stop.assert_not_called()


def test_unreleased_lock_refuses_instead_of_claiming_stopped(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [])
    monkeypatch.setattr(lifecycle.startup, "_open_start_lock", lambda path: None)
    monkeypatch.setattr(lifecycle, "_STOP_SECONDS", 0.001)
    monkeypatch.setattr(lifecycle, "_KILL_SECONDS", 0.001)
    with pytest.raises(
        lifecycle.ResidentLifecycleError, match="YOKE_HOOK_RESIDENT_LOCK_HELD"
    ) as failure:
        lifecycle.stop_resident()
    assert "close the harness sessions" in str(failure.value)


def test_stop_delegates_escalation_with_start_time_custody(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [(123, 1.0)])
    handle = object()
    rebuild, stop = Mock(return_value=handle), Mock()
    monkeypatch.setattr(platform_process, "handle_from_pid", rebuild)
    monkeypatch.setattr(platform_process, "stop_group", stop)
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: False)
    lifecycle.stop_resident(require_lock_release=False)
    rebuild.assert_called_once_with(123, 1.0)
    stop.assert_called_once_with(handle, timeout=lifecycle._STOP_SECONDS)


def test_an_unkillable_resident_is_named_with_its_pid(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [(123, 1.0)])
    monkeypatch.setattr(platform_process, "handle_from_pid", lambda *args: object())
    monkeypatch.setattr(platform_process, "stop_group", lambda *args, **kwargs: None)
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: True)
    with pytest.raises(lifecycle.ResidentLifecycleError) as failure:
        lifecycle.stop_resident()
    assert "YOKE_HOOK_RESIDENT_STOP_TIMEOUT" in str(failure.value)
    assert "123" in str(failure.value)


def test_restart_accepts_a_resident_a_live_hook_relaunched(monkeypatch, tmp_path):
    monkeypatch.setattr(client.machine_config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(lifecycle, "_resident_processes", lambda paths: [])
    # A live hook's new resident holds the start lock once the old one exits.
    monkeypatch.setattr(lifecycle.startup, "_open_start_lock", lambda path: None)
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
