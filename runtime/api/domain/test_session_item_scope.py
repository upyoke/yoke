"""The item a session holds, or the one it most recently released."""

from __future__ import annotations

from yoke_core.domain.session_item_scope import session_item_scope
from runtime.api.domain.test_session_message_support import (
    NOW_TEXT,
    message_connection,
)


LATER_TEXT = "2026-08-22T18:00:00Z"


def _release(conn, claim_id: int, released_at: str = NOW_TEXT) -> None:
    conn.execute(
        "UPDATE work_claims SET released_at=? WHERE id=?", (released_at, claim_id)
    )
    conn.commit()


def test_a_live_claim_names_the_item_and_its_project() -> None:
    conn = message_connection()

    scope = session_item_scope(conn, "s1")

    assert scope is not None
    assert (scope.item_id, scope.project_id, scope.live) == (101, 1, True)


def test_close_out_leaves_the_released_item_as_the_session_scope() -> None:
    """The DONE report is written at the one moment the claim is gone."""
    conn = message_connection()
    _release(conn, 1)

    scope = session_item_scope(conn, "s1")

    assert scope is not None
    assert (scope.item_id, scope.project_id, scope.live) == (101, 1, False)


def test_the_most_recently_released_item_wins_over_earlier_work() -> None:
    conn = message_connection()
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at,"
        "released_at) VALUES (7,'s1','item','{\"item_id\":201}',?,?)",
        (NOW_TEXT, LATER_TEXT),
    )
    _release(conn, 1)

    scope = session_item_scope(conn, "s1")

    assert scope is not None
    assert (scope.item_id, scope.project_id) == (201, 2)


def test_a_live_claim_outranks_a_later_released_one() -> None:
    conn = message_connection()
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at,"
        "released_at) VALUES (7,'s1','item','{\"item_id\":201}',?,?)",
        (NOW_TEXT, LATER_TEXT),
    )
    conn.commit()

    scope = session_item_scope(conn, "s1")

    assert scope is not None
    assert (scope.item_id, scope.live) == (101, True)


def test_a_session_that_never_held_an_item_has_no_scope() -> None:
    conn = message_connection()

    assert session_item_scope(conn, "s2") is None
    assert session_item_scope(conn, None) is None
