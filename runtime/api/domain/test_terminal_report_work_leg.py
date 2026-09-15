"""One DONE report per work leg: the turn it is sent in, under its claim."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.session_control_human_output import (
    write_message_result,
)
from yoke_contracts.session_control.terminal_report import (
    COLLAPSED_DIFFERING_BODY_NOTICE,
)
from yoke_core.domain.session_item_scope import session_claim_for_item
from yoke_core.domain.session_message_terminal import reporting_turn_marker
from runtime.api.domain.test_session_message_support import (
    NOW_TEXT,
    message_connection,
)
from runtime.api.domain.test_steering_role_addressed_messages import (
    DONE_BODY,
    _message_count,
    _release_item_claim,
    _say_steering,
    _seat,
    _steering_row,
)


def _report_count(conn) -> int:
    """Only the DONE reports; an authorization is a message too."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM session_messages WHERE body LIKE 'DONE %'"
        ).fetchone()[0]
    )


def _resume(conn, *, session_id: str = "s1", at: str) -> None:
    """The worker's turn ended and a later one started, however it was woken.

    ``turn_posture_at`` is what the Stop / UserPromptSubmit hook pair stamps,
    so this is the one fixture shape for every resume route.
    """
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='running', turn_posture_at=? "
        "WHERE session_id=?",
        (at, session_id),
    )
    conn.commit()


def _receive(conn, *, session_id: str = "s1", message_id: str, at: str) -> None:
    """An unrelated message reaches the worker and it acknowledges receipt."""
    conn.execute(
        "INSERT INTO session_messages (message_id,sender_actor_id,body,"
        "body_sha256,selector_snapshot,created_at,expires_at) "
        "VALUES (?,10,'fleet-wide notice','sha','{}',?,?)",
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
    _resume(conn, at="2026-08-22T16:05:00.000000Z")
    second = _say_steering(conn, body="DONE ALP-1 retest green after resume.")

    assert session_claim_for_item(conn, "s1", 101).live is True
    assert session_claim_for_item(conn, "s1", 101).claim_id == 1
    assert second["message_id"] != first["message_id"]
    assert second["deduplicated"] is False
    assert _report_count(conn) == 2


def test_retries_inside_one_turn_still_collapse() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")
    _resume(conn, at="2026-08-22T16:05:00.000000Z")

    first = _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=f"{DONE_BODY} Merged and green.")

    assert retry["message_id"] == first["message_id"]
    assert retry["deduplicated"] is True
    assert _report_count(conn) == 1


def test_an_unrelated_receipt_mid_turn_does_not_open_a_leg() -> None:
    """Receiving mail is not being resumed, so a retry after it still collapses."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    first = _say_steering(conn, body=DONE_BODY)
    _receive(conn, message_id="m-broadcast", at="2026-08-22T16:05:00Z")
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


def test_a_person_resuming_the_worker_opens_a_leg_like_any_other_wake() -> None:
    """No message is involved, and the second completion still reaches the seat."""
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    first = _say_steering(conn, body=DONE_BODY)
    _resume(conn, at="2026-08-22T16:07:00.000000Z")
    second = _say_steering(conn, body="DONE ALP-1 follow-up the operator asked for.")

    assert second["message_id"] != first["message_id"]
    assert _report_count(conn) == 2
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_recipients WHERE session_id='s1'"
        ).fetchone()[0]
        == 0
    )


def test_a_surface_with_no_recorded_turn_still_keys_on_its_claim() -> None:
    conn = message_connection()
    _seat(conn, claim_id=10, session_id="s2")

    assert reporting_turn_marker(conn, "s1") is None

    first = _say_steering(conn, body=DONE_BODY)
    retry = _say_steering(conn, body=DONE_BODY)
    _release_item_claim(conn)
    _reacquire_alpha(conn)
    resumed = _say_steering(conn, body="DONE ALP-1 second leg on a fresh claim.")

    assert retry["message_id"] == first["message_id"]
    assert resumed["message_id"] != first["message_id"]
    assert _report_count(conn) == 2
