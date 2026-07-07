"""Regression coverage for session-offer charge-invariant cleanup."""

from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.session_contract import ActionKind, NextAction
from yoke_core.api.service_client_sessions_offer_invariant import (
    CLI_SURFACE,
    HTTP_SURFACE,
    OFFER_INVARIANT_FAILED_REASON,
    handle_charge_invariant,
)
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 - re-exported fixture
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(db):
    conn = connect_test_db(db["db_path"])
    return closing(conn)


def _seed_session(conn: Any, session_id: str) -> None:
    now = _iso_now()
    conn.execute(
        """INSERT INTO harness_sessions
            (session_id, executor, provider, model, workspace,
             offered_at, last_heartbeat)
            VALUES (%s, 'DARIUS', 'anthropic', %s, '/tmp/offer-invariant', %s, %s)""",
        (session_id, TEST_MODEL_ID, now, now),
    )
    conn.commit()


def _seed_offer_time_claim(
    conn: Any, session_id: str, item_id: int,
) -> int:
    now = _iso_now()
    cur = conn.execute(
        """INSERT INTO work_claims
            (session_id, target_kind, item_id, claim_type,
             claimed_at, last_heartbeat)
            VALUES (%s, 'item', %s, 'exclusive', %s, %s) RETURNING id""",
        (session_id, item_id, now, now),
    )
    claim_id = int(cur.fetchone()[0])
    conn.commit()
    return claim_id


def _make_charge_action(
    selected: Optional[str],
    scheduler_block: Optional[dict] = None,
) -> NextAction:
    context: dict[str, object] = {}
    if selected is not None:
        context["selected_item"] = selected
    if scheduler_block is not None:
        context["scheduler"] = scheduler_block
    return NextAction(
        action=ActionKind.CHARGE,
        reason="test",
        chainable=True,
        correlation_id="invariant-test",
        context=context,
    )


def _active_claim_count(conn: Any, session_id: str, item_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM work_claims "
        "WHERE session_id=%s AND item_id=%s AND released_at IS NULL",
        (session_id, item_id),
    ).fetchone()[0]


def _read_invariant_event(conn: Any, session_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT envelope FROM events "
        "WHERE session_id=%s AND event_name='SessionOfferInvariantFailed' "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return None
    envelope = row[0]
    return json.loads(envelope) if isinstance(envelope, str) else envelope


def _next_action_count(conn: Any, session_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM events "
        "WHERE session_id=%s AND event_name='NextActionChosen'",
        (session_id,),
    ).fetchone()[0]


@pytest.fixture
def invariant_db(session_offer_db, monkeypatch):
    monkeypatch.setenv("YOKE_DB", session_offer_db["db_path"])
    monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)
    monkeypatch.delenv("YOKE_EVENTS_CAPTURE", raising=False)
    return session_offer_db


def test_mismatched_claim_releases_exact_claim_and_emits_event(invariant_db):
    sid = "sess-mismatch-cli"
    held_item_id = 10
    wrong_selected = "YOK-12"

    with _connect(invariant_db) as conn:
        _seed_session(conn, sid)
        claim_id = _seed_offer_time_claim(conn, sid, held_item_id)
        ok, err = handle_charge_invariant(
            conn,
            session_id=sid,
            result=_make_charge_action(
                wrong_selected,
                {"selected_item": wrong_selected, "next_step": "advance"},
            ),
            new_claim={"id": claim_id, "item_id": held_item_id},
            ownership={
                "chain_skip_memory": [
                    {"item_id": held_item_id, "reason": "irrelevant", "chain_step": 1},
                ],
            },
            surface=CLI_SURFACE,
        )

    assert ok is False
    assert err is not None
    assert "does not match" in err

    with _connect(invariant_db) as conn:
        assert _active_claim_count(conn, sid, held_item_id) == 0
        envelope = _read_invariant_event(conn, sid)
        assert _next_action_count(conn, sid) == 0

    assert envelope is not None, "SessionOfferInvariantFailed must be emitted"
    ctx = envelope.get("context") or {}
    assert ctx["action"] == "charge"
    assert ctx["selected_item"] == wrong_selected
    assert ctx["schedule_selected_item"] == wrong_selected
    assert ctx["new_claim"] == {"claim_id": claim_id, "item_id": held_item_id}
    assert ctx["surface"] == CLI_SURFACE
    assert ctx["invariant_message"] == err
    assert ctx["retry_skip_summary"] == [
        {"item_id": str(held_item_id), "reason": "irrelevant", "chain_step": 1},
    ]
    assert ctx["release_outcome"]["released"] is True
    assert ctx["release_outcome"]["reason_intent"] == OFFER_INVARIANT_FAILED_REASON


def test_charge_without_claim_emits_event_without_release_attempt(invariant_db):
    sid = "sess-no-claim-http"

    with _connect(invariant_db) as conn:
        _seed_session(conn, sid)
        ok, err = handle_charge_invariant(
            conn,
            session_id=sid,
            result=_make_charge_action("YOK-10"),
            new_claim=None,
            ownership={"chain_skip_memory": []},
            surface=HTTP_SURFACE,
        )

    assert ok is False
    assert err is not None
    assert "without a backing work claim" in err

    with _connect(invariant_db) as conn:
        envelope = _read_invariant_event(conn, sid)

    assert envelope is not None
    ctx = envelope.get("context") or {}
    assert ctx["new_claim"] is None
    assert ctx["surface"] == HTTP_SURFACE
    assert "release_outcome" not in ctx


def test_matching_claim_passes_through_without_event_or_release(invariant_db):
    sid = "sess-happy"
    held_item_id = 10

    with _connect(invariant_db) as conn:
        _seed_session(conn, sid)
        claim_id = _seed_offer_time_claim(conn, sid, held_item_id)
        ok, err = handle_charge_invariant(
            conn,
            session_id=sid,
            result=_make_charge_action(f"YOK-{held_item_id}"),
            new_claim={"id": claim_id, "item_id": held_item_id},
            ownership={"chain_skip_memory": []},
            surface=CLI_SURFACE,
        )

    assert ok is True
    assert err is None

    with _connect(invariant_db) as conn:
        assert _active_claim_count(conn, sid, held_item_id) == 1
        assert _read_invariant_event(conn, sid) is None


def test_event_registered_in_authoritative_table():
    from yoke_core.domain.populate_registry_data_authoritative import AUTHORITATIVE_METADATA
    assert "SessionOfferInvariantFailed" in {row[0] for row in AUTHORITATIVE_METADATA}
