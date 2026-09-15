"""Terminal DONE reports bind identity to the heading's item and work leg."""

from __future__ import annotations

import io

import pytest

from yoke_cli.commands.adapters.session_control_human_output import (
    write_message_result,
)
from yoke_contracts.session_control.terminal_report import (
    COLLAPSED_DIFFERING_BODY_NOTICE,
    parse_terminal_report,
)
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


def _report_count(conn) -> int:
    """Only the DONE reports; an authorization is a message too."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM session_messages WHERE body LIKE 'DONE %'"
        ).fetchone()[0]
    )


def _authorize(conn, *, session_id: str = "s1", message_id: str, at: str) -> None:
    """Steering instructed the worker, and the worker acknowledged it."""
    conn.execute(
        "INSERT INTO session_messages (message_id,sender_actor_id,body,"
        "body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES (?,10,'resume and retest','sha','{}',?,?)",
        (message_id, at, at),
    )
    conn.execute(
        "INSERT INTO session_message_recipients (message_id,session_id,"
        "project_id,resolution_evidence,routing_snapshot,state,created_at,"
        "wake_after,acknowledged_at) "
        "VALUES (?,?,1,'[]','{}','acknowledged',?,?,?)",
        (message_id, session_id, at, at, at),
    )
    conn.commit()


def _reacquire_alpha(conn, *, session_id: str = "s1", claim_id: int = 20) -> None:
    """Steering resumed the worker, so it holds ALP-1 on a fresh claim."""
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'item','{\"item_id\":101}',?)",
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
    exact = _say_steering(conn, body=DONE_BODY)

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    # The reworded body was discarded, so the caller is told rather than left
    # reading a collapse as a delivery.
    assert retry["collapsed_differing_body"] is True
    assert exact["message_id"] == first["message_id"]
    assert "collapsed_differing_body" not in exact
    assert _message_count(conn) == 1


def test_a_completion_after_reacquire_is_a_new_report() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    first = _say_steering(conn, body=DONE_BODY)
    _release_item_claim(conn)
    _reacquire_alpha(conn)
    second = _say_steering(conn, body="DONE ALP-1 resumed follow-up landed.")

    assert second["message_id"] != first["message_id"]
    assert second["deduplicated"] is False
    assert _message_count(conn) == 2
    assert [r["session_id"] for r in second["recipients"]] == ["s2"]
    assert _steering_row(conn, second["message_id"])["sender_item_id"] == 101


def test_a_retained_lane_reports_its_resumed_completion() -> None:
    """A worker kept on its live claim for delivery still reaches the seat."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    first = _say_steering(conn, body=DONE_BODY)
    _authorize(conn, message_id="m-resume", at="2026-08-22T16:05:00Z")
    second = _say_steering(conn, body="DONE ALP-1 retest green after resume.")

    assert session_claim_for_item(conn, "s1", 101).live is True
    assert second["message_id"] != first["message_id"]
    assert second["deduplicated"] is False
    assert _report_count(conn) == 2


def test_retries_under_one_authorization_still_collapse() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _authorize(conn, message_id="m-resume", at="2026-08-22T16:05:00Z")

    first = _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=f"{DONE_BODY} Merged and green.")

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    assert _report_count(conn) == 1


def test_a_retry_after_close_out_released_the_leg_still_collapses() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    first = _say_steering(conn, body=DONE_BODY)
    _release_item_claim(conn)
    retry = _say_steering(conn, body=DONE_BODY)

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    assert _message_count(conn) == 1


def test_another_session_reporting_the_same_item_is_its_own_leg() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _reacquire_alpha(conn, session_id="s4", claim_id=21)

    first = _say_steering(conn, body=DONE_BODY)
    other = _say_steering(conn, sender="s4", body=DONE_BODY)

    assert other["message_id"] != first["message_id"]
    assert _message_count(conn) == 2


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


def test_the_send_summary_names_a_collapse_that_discarded_the_body() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=f"{DONE_BODY} Merged and green.")

    rendered = io.StringIO()
    write_message_result(retry, rendered)

    assert COLLAPSED_DIFFERING_BODY_NOTICE in rendered.getvalue()


def test_the_send_summary_stays_quiet_when_nothing_was_discarded() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    sent = _say_steering(conn, body=DONE_BODY)

    rendered = io.StringIO()
    write_message_result(sent, rendered)

    assert COLLAPSED_DIFFERING_BODY_NOTICE not in rendered.getvalue()
