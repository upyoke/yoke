"""Procfs process identity stays safe with truncated comm and no ps binary."""

from pathlib import Path
import time
from unittest.mock import patch

import pytest

from yoke_contracts import linux_process_snapshot, process_ancestry


@pytest.fixture
def proc(tmp_path):
    (tmp_path / "stat").write_text("cpu 1 2 3\nbtime 1000\n")
    with (
        patch.object(linux_process_snapshot, "_PROC_ROOT", tmp_path),
        patch.object(process_ancestry.sys, "platform", "linux"),
        patch.object(process_ancestry.subprocess, "run", side_effect=FileNotFoundError),
        patch.object(linux_process_snapshot.os, "sysconf", return_value=100),
    ):
        yield tmp_path


def add_process(proc, pid, parent, name, *, state="S", start="12345"):
    directory = proc / str(pid)
    directory.mkdir()
    # stat fields 3..22; comm can contain spaces and parentheses.
    fields = [state, str(parent), *(["0"] * 17), start]
    (directory / "stat").write_text(f"{pid} ({name[:15]}) " + " ".join(fields))
    (directory / "cmdline").write_bytes(name.encode() + b"\0--argument\0")
    return directory


@pytest.mark.parametrize("name", ["codex-code-mode-host", "claude bg-pty-host"])
def test_full_name_stops_walk_before_shared_host_without_ps(proc, name):
    add_process(proc, 100, 1, "claude")
    add_process(proc, 200, 100, name)
    add_process(proc, 300, 200, "/usr/bin/bash")
    add_process(proc, 400, 300, "/usr/bin/python3")
    assert process_ancestry.process_command_name(200) == name
    assert process_ancestry.process_table()[200] == (100, name)
    assert process_ancestry.ancestor_pids(400) == [300, 200, 100, 1]
    assert process_ancestry.anchor_candidate_pids(400) == [300]
    assert process_ancestry.find_nearest_harness_anchor(400) is None


def test_per_session_anchor_resolves_without_ps(proc):
    add_process(proc, 200, 1, "/opt/Claude App/claude", start="777")
    add_process(proc, 300, 200, "bash")
    anchor = process_ancestry.find_nearest_harness_anchor(300)
    assert anchor == process_ancestry.ProcessAnchor(200, time.ctime(1007.77), "claude")
    # Existing idle-host cleanup parses the same calendar format as ps lstart.
    assert time.strptime(anchor.start_time, "%a %b %d %H:%M:%S %Y")


def test_stat_parentheses_and_pid_reuse(proc):
    directory = add_process(proc, 200, 100, "weird ) name", start="111")
    assert process_ancestry.parent_map() == {200: 100}
    assert process_ancestry.process_start_time(200) == time.ctime(1001.11)
    (directory / "stat").write_text(
        (directory / "stat").read_text().replace("111", "222")
    )
    assert process_ancestry.process_start_time(200) == time.ctime(1002.22)


def test_missing_boot_time_cannot_supply_start_identity(proc):
    add_process(proc, 200, 1, "claude")
    (proc / "stat").write_text("cpu 1 2 3\n")
    assert process_ancestry.process_start_time(200) is None


def test_zombie_and_disappeared_processes_are_not_live(proc):
    add_process(proc, 200, 1, "claude", state="Z")
    (proc / "300").mkdir()  # Exited between enumeration and stat read.
    (proc / "400").mkdir()
    (proc / "400" / "stat").write_text("malformed")
    assert process_ancestry.process_start_time(200) is None
    assert process_ancestry.process_start_time(300) is None
    assert process_ancestry.process_start_time(400) is None
    assert set(process_ancestry.process_table()) == {200}


@pytest.mark.parametrize("cmdline", [b"", None])
def test_exe_supplies_name_when_cmdline_is_unavailable(proc, cmdline):
    directory = add_process(proc, 200, 1, "claude")
    if cmdline is None:
        with patch.object(Path, "read_bytes", side_effect=PermissionError):
            (directory / "exe").symlink_to("/opt/host/codex-code-mode-host")
            assert process_ancestry.process_command_name(200) == "codex-code-mode-host"
    else:
        (directory / "cmdline").write_bytes(cmdline)
        (directory / "exe").symlink_to("/opt/host/codex-code-mode-host")
        assert process_ancestry.process_command_name(200) == "codex-code-mode-host"


def test_nameless_process_keeps_parent_link_and_missing_proc_is_empty(proc):
    directory = add_process(proc, 200, 100, "")
    (directory / "cmdline").write_bytes(b"")
    assert process_ancestry.process_table() == {200: (100, "")}
    with patch.object(linux_process_snapshot, "_PROC_ROOT", proc / "absent"):
        assert process_ancestry.process_table() == {}
