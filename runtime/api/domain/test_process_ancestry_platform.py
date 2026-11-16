"""Native process snapshots preserve identity and shared-host boundaries."""

from unittest.mock import Mock

import pytest

from yoke_contracts import platform_process, process_ancestry

pytestmark = pytest.mark.windows


def entry(pid, ppid, name, started=123.5):
    return platform_process.ProcessInfo(pid, ppid, (name,), started, name, 10, "owner")


@pytest.mark.parametrize("name", ["codex-code-mode-host", "claude bg-pty-host",
                                  "cursor-agent.exe"])
def test_full_name_stops_before_shared_host_without_ps(monkeypatch, name):
    rows = [entry(100, 1, "claude"), entry(200, 100, name),
            entry(300, 200, "/bin/bash"), entry(400, 300, "python.exe")]
    monkeypatch.setattr(platform_process, "process_command_lines", lambda: rows)
    assert process_ancestry.process_command_name(200) == name
    assert process_ancestry.process_table()[200] == (100, name)
    assert process_ancestry.anchor_candidate_pids(400) == [300]
    assert process_ancestry.find_nearest_harness_anchor(400) is None


def test_exact_creation_epoch_changes_on_pid_reuse(monkeypatch):
    rows = [entry(200, 100, "claude", 123.5)]
    monkeypatch.setattr(platform_process, "process_command_lines", lambda: rows)
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: True)
    assert process_ancestry.process_start_time(200) == "123.5"
    rows[0] = entry(200, 100, "claude", 123.6)
    assert process_ancestry.process_start_time(200) == "123.6"


def test_exit_during_snapshot_never_yields_a_live_identity(monkeypatch):
    monkeypatch.setattr(platform_process, "process_command_lines",
                        lambda: [entry(200, 1, "claude")])
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: False)
    assert process_ancestry.process_start_time(200) is None


def test_unobservable_identity_is_not_reported_live(monkeypatch):
    monkeypatch.setattr(platform_process, "process_command_lines",
                        lambda: [entry(200, 1, "claude")])
    monkeypatch.setattr(platform_process, "pid_alive",
                        Mock(side_effect=OSError("process_access_denied")))
    with pytest.raises(OSError, match="process_access_denied"):
        process_ancestry.process_start_time(200)
