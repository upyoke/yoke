"""Quoted task-notification text must not settle a live Bash row.

Claude settings do not subscribe ``Notification``. UserPromptSubmit stdin
has no captured native-source discriminator at the hook boundary (the
transcript's ``origin.kind=task-notification`` is a different record).
Ordinary prompt/message/content XML therefore must leave the row open.
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

QUOTED_NOTIFICATION = (
    "<task-notification>\n"
    "<task-id>b2w7e29pn</task-id>\n"
    f"<tool-use-id>{BASH_ID}</tool-use-id>\n"
    "<status>failed</status>\n"
    "<summary>example quoted in an ordinary prompt</summary>\n"
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
    monkeypatch.setattr(session_dispatch, "_run_claude_prompt_submit", lambda *_a: "")


def _evaluate(event_name: str, payload: dict, *, family: str = "claude") -> None:
    session_dispatch.evaluate(
        HookContext(
            event_name=event_name,
            executor_family=family,
            executor_surface="cli",
            payload=payload,
            session_id=SESSION,
            remote=True,
        )
    )


def test_quoted_prompt_xml_does_not_close_bash(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _evaluate(
        "UserPromptSubmit",
        {"prompt": QUOTED_NOTIFICATION, "session_id": SESSION},
    )
    assert _row(conn, BASH_ID)[0] is None
    assert live_stop_block_reason(conn, SESSION) == gate.REASON_LIVE_COMMAND


def test_unsubscribed_notification_event_does_not_close_bash(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _evaluate(
        "Notification",
        {"message": QUOTED_NOTIFICATION, "session_id": SESSION},
    )
    assert _row(conn, BASH_ID)[0] is None
    assert live_stop_block_reason(conn, SESSION) == gate.REASON_LIVE_COMMAND


def test_transcript_origin_on_prompt_is_not_hook_authority(conn, monkeypatch) -> None:
    _start(conn, tool_use_id=BASH_ID, tool_name="Bash", command="sleep 200")
    _post(conn, _background_payload())
    _arm_dispatch(conn, monkeypatch)
    _evaluate(
        "UserPromptSubmit",
        {
            "prompt": QUOTED_NOTIFICATION,
            "session_id": SESSION,
            "origin": {"kind": "task-notification"},
        },
    )
    assert _row(conn, BASH_ID)[0] is None


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
