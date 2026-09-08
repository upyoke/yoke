"""Terminal DONE reports bind identity to the named PREFIX-N heading."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.terminal_report import parse_terminal_report
from yoke_core.domain.session_item_scope import session_claim_for_item
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_terminal import (
    ITEM_UNKNOWN,
    ITEM_UNRELATED,
    ITEM_UNSPECIFIED,
)
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.steering_message_drain import drain_to_seat
from yoke_core.domain.steering_message_recipients import STATE_AWAITING_SEAT
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    DONE_BODY,
    PROJECT_SCOPE,
    _message_count,
    _release_item_claim,
    _say_steering,
    _seat,
    _steering_row,
)


DONE_BET = "DONE BET-1 companion close-out landed."


def _hold_beta(conn, *, session_id: str = "s1", claim_id: int = 8) -> None:
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'item','{\"item_id\":201}',?)",
        (claim_id, session_id, NOW_TEXT),
    )
    conn.commit()


def test_parse_reads_only_the_heading_prefix_n() -> None:
    parsed = parse_terminal_report("DONE ALP-1 close-out landed.\nAlso BET-1.")
    assert parsed is not None
    assert parsed.item_ref == "ALP-1"
    assert parse_terminal_report("Blocked: ALP-1 is still red.") is None
    missing = parse_terminal_report("DONE close-out landed.")
    assert missing is not None and missing.item_ref is None


def test_released_a_while_holding_b_keys_and_addresses_a() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _seat(conn, claim_id=11, session_id="s3", scope='{"project_id":2}')
    _release_item_claim(conn)
    _hold_beta(conn)

    sent = _say_steering(conn, body=DONE_BODY)

    assert [r["session_id"] for r in sent["recipients"]] == ["s2"]
    assert _steering_row(conn, sent["message_id"])["sender_item_id"] == 101
    assert _steering_row(conn, sent["message_id"])["project_id"] == 1
    assert session_claim_for_item(conn, "s1", 201) is not None
    assert session_claim_for_item(conn, "s1", 101) is not None
    assert session_claim_for_item(conn, "s1", 101).live is False


def test_distinct_a_and_b_reports_are_separate_messages() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _seat(conn, claim_id=11, session_id="s3", scope='{"project_id":2}')
    _release_item_claim(conn)
    _hold_beta(conn)

    first = _say_steering(conn, body=DONE_BODY)
    second = _say_steering(conn, body=DONE_BET)

    assert second["message_id"] != first["message_id"]
    assert _message_count(conn) == 2
    assert _steering_row(conn, second["message_id"])["sender_item_id"] == 201
    assert [r["session_id"] for r in second["recipients"]] == ["s3"]


def test_reworded_retry_of_the_named_item_is_the_same_report() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _release_item_claim(conn)
    _hold_beta(conn)

    first = _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=f"{DONE_BODY} Merged and green.")

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    assert _message_count(conn) == 1


def test_unrelated_and_unknown_headings_refuse_instead_of_guessing() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    with pytest.raises(SessionMessageError) as unrelated:
        _say_steering(conn, body=DONE_BET)
    assert unrelated.value.code == ITEM_UNRELATED

    with pytest.raises(SessionMessageError) as unknown:
        _say_steering(conn, body="DONE ZZZ-9 never existed.")
    assert unknown.value.code == ITEM_UNKNOWN

    with pytest.raises(SessionMessageError) as unspecified:
        _say_steering(conn, body="DONE close-out landed.")
    assert unspecified.value.code == ITEM_UNSPECIFIED


def test_a_queued_terminal_report_still_drains_to_the_next_seat() -> None:
    conn = message_connection()
    parked = _say_steering(conn, body=DONE_BODY)
    assert _steering_row(conn, parked["message_id"])["state"] == STATE_AWAITING_SEAT

    _seat(conn, claim_id=10, session_id="s2")
    handoff = drain_to_seat(
        conn,
        scope=PROJECT_SCOPE,
        project_id=1,
        session_id="s2",
        claim_id=10,
        descriptor="alpha",
        now=NOW,
    )
    conn.commit()

    assert handoff["drained_count"] == 1
    assert _steering_row(conn, parked["message_id"])["seat_session_id"] == "s2"


def test_ordinary_nonterminal_mail_still_uses_the_live_claim() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _seat(conn, claim_id=11, session_id="s3", scope='{"project_id":2}')
    _release_item_claim(conn)
    _hold_beta(conn)

    sent = _say_steering(conn, body="Blocked: the merge gate went red.")

    assert [r["session_id"] for r in sent["recipients"]] == ["s3"]
    assert _steering_row(conn, sent["message_id"])["sender_item_id"] == 201


def test_a_session_less_done_report_is_refused() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError) as raised:
        send_message(
            conn,
            actor_id=10,
            sender_session_id=None,
            selector=selector(steering=True, steering_scope=PROJECT_SCOPE),
            body=DONE_BODY,
            now=NOW,
        )
    assert raised.value.code == ITEM_UNSPECIFIED
