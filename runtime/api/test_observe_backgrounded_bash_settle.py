"""Background Bash settles on Claude's task-notification, not TaskOutput.

Completion is ``<task-notification>`` on Notification or UserPromptSubmit
carrying the original Bash ``tool-use-id``. TaskOutput uses another id.
A ``stopped`` notification is the session-ended cancel path; SessionEnd
still runs the existing orphan sweep on a full schema.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.session_tool_call_projections import live_stop_block_reason
from yoke_core.hooks import session_dispatch
from yoke_core.hooks.types import HookContext
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.observe_full_test_helpers import make_events_db_conn
from runtime.api.test_observe_backgrounded_bash_stop import (
    BASH_ID,
    SESSION,
    _SESSION_DDL,
    _background_payload,
    _post,
    _row,
    _start,
)

TASK_OUTPUT_ID = "toolu_01TaskOutputOtherId"

FAILED_NOTIFICATION = (
    "<task-notification>\n"
    "<task-id>b2w7e29pn</task-id>\n"
    f"<tool-use-id>{BASH_ID}</tool-use-id>\n"
    "<output-file>/tmp/b2w7e29pn.output</output-file>\n"
    "<status>failed</status>\n"
    "<summary>Background command failed with exit code 1</summary>\n"
    "</task-notification>"
)

STOPPED_NOTIFICATION = (
    "<task-notification>\n"
    "<task-id>bep007lkn</task-id>\n"
    f"<tool-use-id>{BASH_ID}</tool-use-id>\n"
    "<status>stopped</status>\n"
    "<summary>Background shell command didn't finish before the "
    "previous session ended</summary>\n"
    "</task-notification>"
)


@pytest.fixture
def conn():
    db = make_events_db_conn()
    apply_fixture_ddl(db, _SESSION_DDL)
    db.execute(
        "INSERT INTO harness_sessions (session_id, mode) VALUES (%s, %s)",
        (SESSION, "dash"),
    )
    db.commit()
    yield db
    db.close()


def _arm_dispatch(conn, monkeypatch) -> None:
    monkeypatch.setattr(conn, "close", lambda: None)
    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: conn)
    monkeypatch.setattr(
        session_dispatch,
        "_root_and_db",
        lambda _c: ("/Users/x/yoke", "/tmp/yoke.db"),
    )
    monkeypatch.setattr(session_dispatch, "_is_yoke_target", lambda *_a: True)
    monkeypatch.setattr(
        session_dispatch, "_run_claude_prompt_submit", lambda *_a: ""
    )


def _notify(event_name: str, text: str, *, key: str) -> None:
    session_dispatch.evaluate(
        HookContext(
            event_name=event_name,
            executor_family="claude",
            executor_surface="cli",
            payload={key: text, "session_id": SESSION},
            session_id=SESSION,
            remote=True,
        )
    )


def test_task_notification_closes_original_bash_id(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _notify("Notification", FAILED_NOTIFICATION, key="message")
    row = _row(conn, BASH_ID)
    assert row[0] is not None
    assert row[1] == "failed"
    assert live_stop_block_reason(conn, SESSION) is None


def test_prompt_submit_notification_is_idempotent_with_notification(
    conn, monkeypatch
) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _notify("Notification", FAILED_NOTIFICATION, key="message")
    _notify("UserPromptSubmit", FAILED_NOTIFICATION, key="prompt")
    assert _row(conn, BASH_ID)[1] == "failed"
    assert live_stop_block_reason(conn, SESSION) is None


def test_stopped_notification_closes_as_interrupted(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _notify("Notification", STOPPED_NOTIFICATION, key="message")
    row = _row(conn, BASH_ID)
    assert row[0] is not None
    assert row[1] == "interrupted"
    assert live_stop_block_reason(conn, SESSION) is None


def test_task_output_other_id_does_not_close_bash(conn) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _start(conn, tool_use_id=TASK_OUTPUT_ID, tool_name="TaskOutput")
    _post(
        conn,
        {
            "tool_name": "TaskOutput",
            "tool_input": {"task_id": "bep007lkn"},
            "tool_response": {"content": "still running"},
            "tool_use_id": TASK_OUTPUT_ID,
            "session_id": SESSION,
        },
    )
    assert _row(conn, BASH_ID)[0] is None
    assert _row(conn, TASK_OUTPUT_ID)[0] is not None
    assert live_stop_block_reason(conn, SESSION) == gate.REASON_LIVE_COMMAND
