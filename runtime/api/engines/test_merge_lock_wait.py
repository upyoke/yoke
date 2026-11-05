"""Deterministic merge lock wait and acquire races."""

import pytest

from yoke_core.domain import merge_lock, runtime_settings
from yoke_core.engines import merge_lock_wait as wait


@pytest.mark.parametrize("race", [False, True])
def test_waits_and_acquires_after_block_clears(monkeypatch, race):
    scope = merge_lock.LockScope("project", "main")
    handle = merge_lock.LockHandle("holder", "ITEM-2", scope)
    checks = iter(
        ["Merge lock held by ITEM-1", None, "Merge lock held by ITEM-3", None]
    )
    sleeps, lines, attempts = [], [], []
    monkeypatch.setattr(runtime_settings, "get_int", lambda *_: 1)
    monkeypatch.setattr(merge_lock, "check", lambda **_: next(checks))

    def acquire(*args, **kwargs):
        attempts.append(args)
        if race and len(attempts) == 1:
            raise merge_lock.MergeLockHeld("lost race")
        return handle

    monkeypatch.setattr(merge_lock, "acquire", acquire)
    result = wait.wait_and_acquire(
        scope,
        "ITEM-2",
        None,
        print_fn=lines.append,
        sleep_fn=sleeps.append,
        clock=lambda: sum(sleeps),
    )
    assert result is handle
    assert sleeps == [15] * (2 if race else 1)
    assert "ITEM-1" in lines[0]
    assert all("project/main" in line for line in lines)
    if race:
        assert "ITEM-3" in lines[1]


def test_timeout_keeps_last_holder_and_waits_full_ttl(monkeypatch):
    sleeps, lines = [], []
    monkeypatch.setattr(runtime_settings, "get_int", lambda *_: 1)
    monkeypatch.setattr(merge_lock, "check", lambda **_: "Merge lock held by ITEM-1")
    monkeypatch.setattr(merge_lock, "acquire", lambda *a, **k: pytest.fail("blocked"))
    result = wait.wait_and_acquire(
        merge_lock.LockScope("project", "main"),
        "ITEM-2",
        None,
        print_fn=lines.append,
        sleep_fn=sleeps.append,
        clock=lambda: sum(sleeps),
    )
    assert result == "Merge lock held by ITEM-1"
    assert sleeps == [15] * 4
    assert len(lines) == 5
    assert "elapsed 1m00s of 1m" in lines[-1]


def test_clear_lock_acquires_without_sleep(monkeypatch):
    handle = merge_lock.LockHandle("holder", "ITEM-1")
    monkeypatch.setattr(runtime_settings, "get_int", lambda *_: 1)
    monkeypatch.setattr(merge_lock, "check", lambda **_: None)
    monkeypatch.setattr(merge_lock, "acquire", lambda *a, **k: handle)
    assert (
        wait.wait_and_acquire(
            merge_lock.LockScope(),
            "ITEM-1",
            None,
            print_fn=lambda _: pytest.fail("clear"),
            sleep_fn=lambda _: pytest.fail("clear"),
        )
        is handle
    )
