"""The one rule deciding which steering seat covers which work."""

from __future__ import annotations

from yoke_core.domain.steering_scope_coverage import (
    covering_claims,
    covering_seat,
    scope_specificity,
    scopes_overlap,
    steering_scope_covers,
)
from runtime.api.domain.test_session_message_support import (
    NOW_TEXT,
    message_connection,
)


def _steering_claim(conn, *, claim_id: int, session_id: str, scope: str) -> None:
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (?,?,'steering',?,?)",
        (claim_id, session_id, scope, NOW_TEXT),
    )
    conn.commit()


def test_project_scope_covers_every_item_in_that_project() -> None:
    assert steering_scope_covers({"project_id": 1}, {"project_id": 1})
    assert steering_scope_covers({"project_id": 1}, {"project_id": 1, "item_id": 101})
    assert not steering_scope_covers({"project_id": 1}, {"project_id": 2})


def test_a_refinement_must_match_the_addressed_work() -> None:
    """A finer seat covers only the work its refinement names."""
    scope = {"project_id": 1, "item_id": 101}
    assert steering_scope_covers(scope, {"project_id": 1, "item_id": 101})
    assert not steering_scope_covers(scope, {"project_id": 1, "item_id": 201})
    assert not steering_scope_covers(scope, {"project_id": 1})


def test_overlap_is_symmetric_and_stops_at_a_disagreeing_refinement() -> None:
    project = {"project_id": 1}
    finer = {"project_id": 1, "item_id": 101}
    other = {"project_id": 1, "item_id": 201}
    assert scopes_overlap(project, finer)
    assert scopes_overlap(finer, project)
    assert not scopes_overlap(finer, other)
    assert not scopes_overlap(project, {"project_id": 2})


def test_specificity_ranks_a_refinement_above_the_project_seat() -> None:
    assert scope_specificity({"project_id": 1, "item_id": 101}) > scope_specificity(
        {"project_id": 1}
    )


def test_the_most_specific_live_seat_receives_the_message() -> None:
    conn = message_connection()
    _steering_claim(conn, claim_id=10, session_id="s1", scope='{"project_id":1}')
    _steering_claim(
        conn, claim_id=11, session_id="s2", scope='{"item_id":101,"project_id":1}'
    )

    covering = covering_claims(conn, {"project_id": 1, "item_id": 101})

    assert [claim["session_id"] for claim in covering] == ["s2", "s1"]
    assert covering_seat(conn, {"project_id": 1, "item_id": 101})["session_id"] == "s2"
    assert covering_seat(conn, {"project_id": 1, "item_id": 201})["session_id"] == "s1"


def test_a_document_seat_covers_only_that_document_s_work() -> None:
    scope = {"project_id": 1, "document": "AREA-PLAN"}
    assert steering_scope_covers(
        scope, {"project_id": 1, "item_id": 101, "document": "AREA-PLAN"}
    )
    assert not steering_scope_covers(
        scope, {"project_id": 1, "item_id": 201, "document": "CURRENT-PLAN"}
    )
    assert not steering_scope_covers(scope, {"project_id": 1, "item_id": 301})


def test_two_document_seats_do_not_overlap_but_the_project_seat_does() -> None:
    project = {"project_id": 1}
    area = {"project_id": 1, "document": "AREA-PLAN"}
    plan = {"project_id": 1, "document": "CURRENT-PLAN"}
    assert scopes_overlap(project, area)
    assert not scopes_overlap(area, plan)


def test_the_document_seat_wins_over_the_project_seat_for_its_work() -> None:
    conn = message_connection()
    _steering_claim(conn, claim_id=10, session_id="s1", scope='{"project_id":1}')
    _steering_claim(
        conn,
        claim_id=11,
        session_id="s2",
        scope='{"document":"AREA-PLAN","project_id":1}',
    )

    linked = {"project_id": 1, "item_id": 101, "document": "AREA-PLAN"}
    assert covering_seat(conn, linked)["session_id"] == "s2"
    assert covering_seat(conn, {"project_id": 1, "item_id": 202})["session_id"] == "s1"


def test_an_ended_session_is_not_a_seat() -> None:
    """Nothing may resolve to an ended session, so nothing resumes one."""
    conn = message_connection()
    _steering_claim(conn, claim_id=10, session_id="s1", scope='{"project_id":1}')
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id='s1'", (NOW_TEXT,)
    )
    conn.commit()

    assert covering_seat(conn, {"project_id": 1}) is None
