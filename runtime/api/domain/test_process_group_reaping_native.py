"""The legacy watcher API retains native process custody through root exit."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.domain import process_group_reaping as reaping


def test_native_spawn_returns_process_with_custody_and_forwards_io(monkeypatch):
    process = Mock(spec=subprocess.Popen)
    handle = SimpleNamespace(process=process)
    spawn = Mock(return_value=handle)
    monkeypatch.setattr(reaping, "spawn_group", spawn)
    result = reaping.popen_in_process_group(
        ["child", "two words"], stdout=subprocess.PIPE,
    )
    assert result is process
    assert result._yoke_process_group is handle
    spawn.assert_called_once_with(["child", "two words"], stdout=subprocess.PIPE)


@pytest.mark.parametrize("failure", [None, PermissionError("survivor refused stop")])
def test_native_stop_keeps_custody_after_leader_exit(monkeypatch, failure):
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = 0
    process._yoke_process_group = handle = object()
    stop = Mock(side_effect=failure)
    monkeypatch.setattr(reaping, "stop_group", stop)
    if failure:
        with pytest.raises(PermissionError, match="survivor refused stop"):
            reaping.terminate_process_group(process, grace_seconds=2)
    else:
        reaping.terminate_process_group(process, grace_seconds=2)
    stop.assert_called_once_with(handle, timeout=2)
    process.poll.assert_not_called()
