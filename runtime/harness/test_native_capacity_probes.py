"""OS capacity readings remain available without daemon PATH lookup."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import native_capacity as capacity
from yoke_harness import session_launch_admission as admission


@pytest.mark.skipif(sys.platform != "darwin", reason="real macOS system probes")
def test_real_macos_probes_with_restricted_daemon_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    reading = capacity.observe_native_capacity()
    assert reading.free_memory_bytes is not None
    assert reading.swap_total_bytes is not None
    assert reading.swap_free_bytes is not None
    assert reading.refusal() != "native_capacity_unreadable"


@pytest.mark.parametrize(
    ("pages", "swap", "code"),
    [
        (262144, "total = 1024M free = 768M", None),
        (1, "total = 1024M free = 768M", "native_memory_headroom_low"),
        (262144, "total = 1024M free = 1M", "native_swap_headroom_low"),
    ],
)
def test_macos_readings_guard_the_spawn(monkeypatch, pages, swap, code):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(
        admission, "observe_native_capacity", capacity.observe_native_capacity
    )
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv == ["/usr/bin/vm_stat"]:
            output = f"page size of 4096 bytes\nPages free: {pages}.\n"
        else:
            assert argv == ["/usr/sbin/sysctl", "-n", "vm.swapusage"]
            output = swap
        return SimpleNamespace(returncode=0, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    started = []
    if code:
        with pytest.raises(admission.NativeCapacityRefusal, match=code):
            admission.spawn_admitted_process(
                ["vendor"], process_factory=lambda *a, **kw: started.append(True)
            )
        assert started == []
    else:
        admission.spawn_admitted_process(
            ["vendor"], process_factory=lambda *a, **kw: started.append(True)
        )
        assert started == [True]
    assert calls == [
        ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
        ["/usr/bin/vm_stat"],
    ]


@pytest.mark.parametrize("probe", ["/usr/bin/vm_stat", "/usr/sbin/sysctl"])
@pytest.mark.parametrize("failure", ["permission", "timeout", "exit", "malformed"])
def test_failed_os_measurement_refuses_before_spawn(monkeypatch, probe, failure):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(
        admission, "observe_native_capacity", capacity.observe_native_capacity
    )

    def run(argv, **kwargs):
        if argv[0] == probe:
            if failure == "permission":
                raise PermissionError("capacity probe denied")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(argv, 2)
            return SimpleNamespace(
                returncode=1 if failure == "exit" else 0, stdout="unreadable"
            )
        return SimpleNamespace(
            returncode=0,
            stdout="total = 1024M free = 768M"
            if argv[0] == "/usr/sbin/sysctl"
            else "page size of 4096 bytes\nPages free: 262144.\n",
        )

    monkeypatch.setattr(subprocess, "run", run)
    started = []
    with pytest.raises(
        admission.NativeCapacityRefusal, match="native_capacity_unreadable"
    ):
        admission.spawn_admitted_process(
            ["vendor"], process_factory=lambda *a, **kw: started.append(True)
        )
    assert started == []
