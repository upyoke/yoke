"""Relay Popen consumers retain the shared OS group handle for cleanup."""

from types import SimpleNamespace

from yoke_harness import session_relay_process_group as groups


def test_spawn_and_stop_use_one_os_group_handle(monkeypatch):
    process = SimpleNamespace(pid=1234)
    handle = SimpleNamespace(pid=1234, process=process)
    spawned, stopped = [], []
    monkeypatch.setattr(groups, "spawn_group", lambda argv, **kw: spawned.append((argv, kw)) or handle)
    monkeypatch.setattr(groups, "stop_group", lambda *args: stopped.append(args) or True)
    assert groups.spawn_relay_process(["native", "arg"], cwd="checkout") is process
    assert spawned == [(["native", "arg"], {"cwd": "checkout"})]
    assert groups.stop_relay_process(process, timeout=3)
    assert stopped == [(handle, 3)]
