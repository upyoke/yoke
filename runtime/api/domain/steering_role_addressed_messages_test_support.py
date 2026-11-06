# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_receipts import acknowledge_message

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_steering import ADDRESS_UNRESOLVED_CODE

from yoke_core.domain.session_message_types import SessionMessageError

from yoke_core.domain.steering_message_drain import DIGEST_BEGIN, drain_to_seat

from yoke_core.domain.steering_message_recipients import (
    STATE_AWAITING_SEAT,
    STATE_DELIVERED,
    awaiting_seat_rows,
    drainable_rows,
)

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)

BODY = "Blocked: the merge gate went red on the schema converge step."

DONE_BODY = "DONE ALP-1 close-out reporting landed."

PROJECT_SCOPE = {"project_id": 1}


def _seat(conn, *, claim_id: int, session_id: str, scope: str = '{"project_id":1}'):
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'steering',?,?)",
        (claim_id, session_id, scope, NOW_TEXT),
    )
    conn.commit()


def _end(conn, session_id: str) -> None:
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, session_id),
    )
    conn.commit()


def _say_steering(conn, *, sender="s1", body=BODY, **selector_values):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id=sender,
        selector=selector(steering=True, **selector_values),
        body=body,
        now=NOW,
    )


def _release_item_claim(conn, claim_id: int = 1) -> None:
    """Close-out releases the item claim before the report is written."""
    conn.execute(
        "UPDATE work_claims SET released_at=? WHERE id=?", (NOW_TEXT, claim_id)
    )
    conn.commit()


def _message_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0])


def _steering_row(conn, message_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM actor_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()
    return dict(row)


def _link_document(conn, item_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO item_strategy_docs "
        "(item_id, project_id, strategy_doc_slug, linked_at) VALUES (?,1,?,?)",
        (item_id, slug, NOW_TEXT),
    )
    conn.commit()
