"""Windows memory facts use the same admission and lane-cap contract on every OS."""

import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import machine_capacity as machine
from yoke_contracts.machine_config import native_capacity as native
from yoke_contracts.timestamps import parse_instant

GIB = 1024**3


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_platform_uses_available_memory_swap_and_machine_lane_cap(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(machine.psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * GIB, available=4 * GIB))
    monkeypatch.setattr(native.psutil, "swap_memory", lambda: SimpleNamespace(total=2 * GIB, free=GIB))
    monkeypatch.setattr(machine.psutil, "getloadavg", lambda: (0.5, 0.4, 0.3))
    reading = native.observe_native_capacity()
    assert reading.free_memory_bytes == 4 * GIB
    assert (reading.swap_total_bytes, reading.swap_free_bytes) == (2 * GIB, GIB)
    assert reading.refusal() is None
    published = machine.observe_machine_capacity({}, observed_at=parse_instant("2026-11-16T18:00:00Z"))
    assert published.total_memory_bytes == 16 * GIB
    assert published.free_memory_bytes == 4 * GIB
    assert published.max_worker_lanes == 8
    assert published.load_average_1m == 0.5


@pytest.mark.parametrize("available,total,free,code", [
    (4 * GIB, 0, 0, None),
    (1, 2 * GIB, GIB, "native_memory_headroom_low"),
    (4 * GIB, 2 * GIB, 1, "native_swap_headroom_low"),
    (4 * GIB, 2 * GIB, 3 * GIB, "native_capacity_unreadable"),
])
def test_windows_headroom_refusals_preserve_existing_admission_rules(monkeypatch, available, total, free, code):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(machine.psutil, "virtual_memory", lambda: SimpleNamespace(total=16 * GIB, available=available))
    monkeypatch.setattr(native.psutil, "swap_memory", lambda: SimpleNamespace(total=total, free=free))
    assert native.observe_native_capacity().refusal() == code


def test_unreadable_windows_system_facts_are_not_fabricated_as_zero(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    def denied():
        raise OSError("system probe denied")
    monkeypatch.setattr(machine.psutil, "virtual_memory", denied)
    monkeypatch.setattr(native.psutil, "swap_memory", denied)
    assert machine.total_memory_bytes() is None
    reading = native.observe_native_capacity()
    assert reading.refusal() == "native_capacity_unreadable"
    assert "unreadable" in reading.reading()
