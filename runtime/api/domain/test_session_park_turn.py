"""Bookkeeping preserves a declared park; ordinary successful work ends it."""

from __future__ import annotations

import json

import pytest

from runtime.api.sessions_test_support import _register, conn  # noqa: F401
from yoke_core.domain.session_mode import set_session_mode
from yoke_core.domain.session_park_turn import unpark_after_work


@pytest.fixture
def parked(conn):  # noqa: F811
    _register(conn)
    set_session_mode(conn, "sess-1", "parked", reason="awaiting delivery")
    return conn


def _envelope(tool_input, tool_name="Bash", **detail):
    return {
        "session_id": "sess-1",
        "tool_name": tool_name,
        "context": {"detail": {"tool_input": tool_input, **detail}},
    }


def _park(db_conn):
    row = db_conn.execute(
        "SELECT mode, quiet_reason FROM harness_sessions WHERE session_id = 'sess-1'"
    ).fetchone()
    return row["mode"], row["quiet_reason"]


@pytest.mark.parametrize(
    "command",
    [
        "yoke events query --session sess-1 --current-episode --json",
        "yoke items progress-log get APP-1",
        "yoke items progress-log append APP-1 --content 'Waiting for delivery'",
        "yoke messages get status-probe --json --full",
        "yoke messages acknowledge status-probe",
        "yoke messages list",
        "yoke sessions touch --mode parked --reason claim",
        "yoke sessions wake schedule --reason 'delivery recheck'",
        "yoke --env prod events query --session sess-1",
        "yoke events query --session sess-1 && yoke messages get status-probe",
        "yoke sessions get",
        "yoke steering report get --json",
        "yoke items get APP-1 status",
        "yoke items list --status implementing",
        "yoke workflows version get dash 12 --json",
        "yoke status",
        "yoke db read 'SELECT 1'",
        "git status --short",
        "git -C /lanes/APP-1 log --oneline -5",
        "cd /lanes/APP-1 && git diff main",
        "yoke events query --session sess-1 && git status --short",
    ],
)
@pytest.mark.parametrize("encoding", ["dict", "json", "raw", "cmd"])
def test_bookkeeping_keeps_mode_and_reason(parked, command, encoding):
    tool_input = {
        "dict": {"command": command},
        "json": json.dumps({"command": command}),
        "raw": command,
        "cmd": {"cmd": command},
    }[encoding]

    assert unpark_after_work(parked, _envelope(tool_input)) is False
    assert _park(parked) == ("parked", "awaiting delivery")


@pytest.mark.parametrize(
    ("shell_kind", "command"),
    [
        (
            "bash",
            "yoke messages get m --json > /dev/null; yoke sessions touch --mode parked --reason r",
        ),
        (
            "bash",
            "yoke messages get m --json 2>&1 && yoke sessions touch --mode=parked --reason r",
        ),
        ("bash", "yoke sessions touch --mode parked --reason r; make build"),
        ("bash", "yoke sessions touch --mode parked; echo 'unfinished"),
        (
            "powershell",
            "yoke messages get m --json > $null; yoke sessions touch --mode parked --reason r",
        ),
        (
            "powershell",
            "yoke messages get m --json | Out-Null; yoke sessions touch `\n --mode parked --reason r",
        ),
    ],
)
def test_explicit_park_survives_its_own_shell_call(parked, shell_kind, command):
    assert unpark_after_work(parked, _envelope(command, shell_kind=shell_kind)) is False
    assert _park(parked) == ("parked", "awaiting delivery")


@pytest.mark.parametrize(
    "command",
    [
        "make build",
        "yoke messages get m --json > out.txt; yoke sessions touch",
        "make build; yoke sessions touch --mode wait",
        "make build; yoke sessions touch --mode=active",
        "make build; yoke sessions touch --reason '--mode parked'",
        "echo 'yoke sessions touch --mode parked'",
        "bash -c 'yoke sessions touch --mode parked'",
        "yoke dev run -- yoke sessions touch --mode parked",
        "rg park docs",
        "cat docs/public/agents/claude.md",
        "yoke events emit --event-name WorkStarted",
        "yoke items scalar set APP-1 --field priority --value high",
        "yoke sessions wake cancel wake-1",
        "yoke events query --session sess-1; cat README.md",
        "yoke events query --session sess-1 | cat",
        "echo 'yoke events query --session sess-1'",
        "yoke items update APP-1 --status implementing",
        "yoke items get APP-1 status > /tmp/status.txt",
        "yoke items get $(cat ref.txt)",
        "yoke say --stdin --steering",
        "yoke packs get starter",
        "git commit -m 'checkpoint'",
        "git branch new-lane",
        "cd /lanes/APP-1 && yoke items update APP-1 --status done",
    ],
)
def test_other_commands_clear_mode_and_reason(parked, command):
    assert unpark_after_work(parked, _envelope({"command": command})) is True
    assert _park(parked) == ("wait", None)


@pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob"])
def test_read_tools_keep_mode_and_reason(parked, tool_name):
    assert unpark_after_work(
        parked, _envelope({"file_path": "README.md"}, tool_name=tool_name)
    ) is False
    assert _park(parked) == ("parked", "awaiting delivery")


def test_wake_then_reads_keeps_park_and_write_ends_it(parked):
    calls = [
        ("Bash", {"command": "yoke messages get wake-1 --json"}),
        ("Bash", {"command": "yoke messages acknowledge wake-1"}),
        ("Bash", {"command": "yoke sessions get"}),
        ("Read", {"file_path": "README.md"}),
        ("Grep", {"pattern": "park", "path": "docs"}),
    ]
    for tool_name, tool_input in calls:
        assert unpark_after_work(parked, _envelope(tool_input, tool_name)) is False
    assert _park(parked) == ("parked", "awaiting delivery")

    write = {"command": "yoke items update APP-1 --status implementing"}
    assert unpark_after_work(parked, _envelope(write)) is True
    assert _park(parked) == ("wait", None)


@pytest.mark.parametrize("tool_name", ["Edit", "Write"])
def test_edit_tools_clear_mode_and_reason(parked, tool_name):
    assert unpark_after_work(
        parked, _envelope({"file_path": "README.md"}, tool_name=tool_name)
    ) is True
    assert _park(parked) == ("wait", None)
