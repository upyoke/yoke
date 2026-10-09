"""The fleet inbox probe reads its wake lines off the compact mailbox page.

The watcher polls ``session_control.message.list`` at the default summary
detail once a minute. These cases drive a real compact page through the
snapshot parser and the inbox alarms, so a projection that drops the
receipts the probe reads fails here instead of silencing every wake.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_core.domain.fleet_delta_alarms import (
    DeltaState,
    inbox_lines,
    starved_envelope_alarms,
)
from yoke_core.domain.fleet_delta_snapshot import ENVELOPES_FUNCTION, read_snapshot
from yoke_core.domain.session_message_page import read_message_page
from yoke_core.domain.session_message_service import send_message
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)

PROBE_SESSION = "s1"
SENDER_SESSION = "s2"


@pytest.fixture(autouse=True)
def _fixed_delivery_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery, session_message_page

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)
    monkeypatch.setattr(session_message_page, "utc_now", lambda: NOW)


def _injected_message(conn) -> str:
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id=SENDER_SESSION,
        selector=selector(session_ids=[PROBE_SESSION]),
        body="please pick up the rebase",
        now=NOW,
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id=?",
        (NOW.isoformat(), sent["message_id"]),
    )
    conn.commit()
    return sent["message_id"]


def _snapshot(conn):
    def call(function_id: str, payload: dict[str, Any]) -> SimpleNamespace:
        assert function_id == ENVELOPES_FUNCTION
        # The probe asks for the default compact page, never bodies.
        assert "detail" not in payload
        page = read_message_page(
            conn,
            actor_id=11,
            caller_session_id=None,
            projects=[1],
            limit=payload["limit"],
        )
        assert page["detail"] == "summary"
        for row in page["messages"]:
            assert "body" not in row
        return SimpleNamespace(success=True, result=page, error=None)

    return read_snapshot(
        [], call=call, now=NOW, self_session_id=PROBE_SESSION, workspace="/w"
    )


def test_an_injected_receipt_on_the_compact_page_wakes_its_recipient() -> None:
    conn = message_connection()
    message_id = _injected_message(conn)
    state = DeltaState()

    first = inbox_lines(_snapshot(conn), state)
    second = inbox_lines(_snapshot(conn), state)

    assert len(first) == 1
    assert f"inbox {message_id} state=injected from={SENDER_SESSION}" in first[0]
    assert second == []


def test_an_injected_receipt_is_not_reported_as_starved() -> None:
    conn = message_connection()
    _injected_message(conn)

    snapshot = _snapshot(conn)
    (row,) = snapshot.envelopes.values()

    assert row.injection_count == 1
    assert starved_envelope_alarms(snapshot, DeltaState()) == []
