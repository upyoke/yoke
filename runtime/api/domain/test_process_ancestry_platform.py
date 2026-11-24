"""Native process snapshots preserve identity and shared-host boundaries."""

from unittest.mock import Mock

import pytest

from yoke_contracts import platform_process, process_ancestry

pytestmark = pytest.mark.windows


def entry(pid, ppid, name, started=123.5):
    return platform_process.ProcessInfo(pid, ppid, (name,), started, name, 10, "owner", started)


def single(monkeypatch, rows):
    """Serve single-PID and ancestor reads; a full-table snapshot fails the test."""
    def info(pid):
        return next((row for row in rows if row.pid == pid), None)

    def ancestors(pid):
        chain, row = [], info(pid)
        while row is not None and info(row.ppid) is not None:
            row = info(row.ppid)
            chain.append(row)
        return chain

    monkeypatch.setattr(platform_process, "process_info", info)
    monkeypatch.setattr(platform_process, "ancestors", ancestors)
    monkeypatch.setattr(platform_process, "process_command_lines",
                        Mock(side_effect=AssertionError("full process snapshot")))


@pytest.mark.parametrize("name", ["codex-code-mode-host", "claude bg-pty-host",
                                  "cursor-agent.exe"])
def test_full_name_stops_before_shared_host_without_ps(monkeypatch, name):
    rows = [entry(100, 1, "claude"), entry(200, 100, name),
            entry(300, 200, "/bin/bash"), entry(400, 300, "python.exe")]
    monkeypatch.setattr(platform_process, "process_command_lines", lambda: rows)
    assert process_ancestry.process_table()[200] == (100, name)
    single(monkeypatch, rows)
    assert process_ancestry.anchor_candidate_pids(400) == [300]
    assert process_ancestry.find_nearest_harness_anchor(400) is None
    assert process_ancestry.process_command_name(200) == name


def test_exact_creation_epoch_changes_on_pid_reuse(monkeypatch):
    rows = [entry(200, 100, "claude", 123.5)]
    single(monkeypatch, rows)
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: True)
    assert process_ancestry.process_start_time(200) == "123.5"
    rows[0] = entry(200, 100, "claude", 123.6)
    assert process_ancestry.process_start_time(200) == "123.6"
    assert process_ancestry.process_start_time(201) is None


def test_exit_during_snapshot_never_yields_a_live_identity(monkeypatch):
    single(monkeypatch, [entry(200, 1, "claude")])
    monkeypatch.setattr(platform_process, "pid_alive", lambda *args: False)
    assert process_ancestry.process_start_time(200) is None


def test_unobservable_identity_is_not_reported_live(monkeypatch):
    single(monkeypatch, [entry(200, 1, "claude")])
    monkeypatch.setattr(platform_process, "pid_alive",
                        Mock(side_effect=OSError("process_access_denied")))
    with pytest.raises(OSError, match="process_access_denied"):
        process_ancestry.process_start_time(200)


def test_single_process_read_matches_the_live_process():
    import os

    info = platform_process.process_info(os.getpid())
    assert info is not None and info.pid == os.getpid()
    assert process_ancestry.process_start_time(os.getpid()) == str(info.start_time)
    assert platform_process.process_info(0) is None


def test_ancestry_table_reads_only_the_process_and_its_ancestors():
    import os

    table = process_ancestry.ancestry_table(os.getpid())
    assert table[os.getpid()][0] == os.getppid()
    assert os.getppid() in table
