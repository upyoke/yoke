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


def _envelope(tool_input, tool_name="Bash"):
    return {
        "session_id": "sess-1",
        "tool_name": tool_name,
        "context": {"detail": {"tool_input": tool_input}},
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
    "command",
    [
        "rg park docs",
        "cat docs/public/agents/claude.md",
        "git status --short",
        "yoke items get APP-1 status",
        "yoke events emit --event-name WorkStarted",
        "yoke items scalar set APP-1 --field priority --value high",
        "yoke sessions wake cancel wake-1",
        "yoke events query --session sess-1 && git status --short",
        "yoke events query --session sess-1; cat README.md",
        "yoke events query --session sess-1 | cat",
        "echo 'yoke events query --session sess-1'",
    ],
)
def test_other_commands_clear_mode_and_reason(parked, command):
    assert unpark_after_work(parked, _envelope({"command": command})) is True
    assert _park(parked) == ("wait", None)


def test_read_tool_clears_mode_and_reason(parked):
    assert unpark_after_work(
        parked, _envelope({"file_path": "README.md"}, tool_name="Read")
    ) is True
    assert _park(parked) == ("wait", None)
