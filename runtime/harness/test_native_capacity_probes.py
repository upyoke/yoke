"""Portable capacity readings guard native spawning without daemon PATH lookup."""

from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import native_capacity as capacity
from yoke_harness import session_launch_admission as admission


def test_real_probes_with_restricted_daemon_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    reading = capacity.observe_native_capacity()
    assert reading.free_memory_bytes is not None
    assert reading.refusal() != "native_capacity_unreadable"


@pytest.mark.parametrize("available,code", [
    (capacity.MIN_NATIVE_FREE_MEMORY_BYTES, None),
    (1, "native_memory_headroom_low"),
])
def test_readings_guard_the_spawn(monkeypatch, available, code):
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(admission, "observe_native_capacity", capacity.observe_native_capacity)
    monkeypatch.setattr(capacity.psutil, "virtual_memory", lambda: SimpleNamespace(available=available))
    monkeypatch.setattr(capacity.psutil, "swap_memory", lambda: SimpleNamespace(total=0, free=0))
    started = []
    if code:
        with pytest.raises(admission.NativeCapacityRefusal, match=code):
            admission.spawn_admitted_process(["vendor"], process_factory=lambda *a, **kw: started.append(True))
        assert started == []
    else:
        admission.spawn_admitted_process(["vendor"], process_factory=lambda *a, **kw: started.append(True))
        assert started == [True]


@pytest.mark.parametrize("failure", [PermissionError("denied"), OSError("probe failed"), capacity.psutil.AccessDenied()])
def test_failed_os_measurement_refuses_before_spawn(monkeypatch, failure):
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(admission, "observe_native_capacity", capacity.observe_native_capacity)
    def fail():
        raise failure
    monkeypatch.setattr(capacity.psutil, "virtual_memory", fail)
    monkeypatch.setattr(capacity.psutil, "swap_memory", lambda: SimpleNamespace(total=0, free=0))
    started = []
    with pytest.raises(admission.NativeCapacityRefusal, match="native_capacity_unreadable"):
        admission.spawn_admitted_process(["vendor"], process_factory=lambda *a, **kw: started.append(True))
    assert started == []
