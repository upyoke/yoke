"""Operator questions follow steering seat coverage, like items and mail.

World: document RELEASES is owned by alpha; beta item LINKED is a member,
beta item PLAIN is unlinked. Alpha and beta each have a project seat; the
RELEASES document seat is taken partway through.
"""

from __future__ import annotations

from unittest.mock import patch

from runtime.api.domain.steering_claim_test_support import (
    HUMAN_ACTOR_ID,
    PROJECT_ALPHA,
    PROJECT_BETA,
    SESSION_ALPHA,
    SESSION_BETA,
    SESSION_GAMMA,
    acquire_steering,
    seed_session,
    seed_standard_steering_world,
    seed_strategy_doc,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_question_filing import file_question
from yoke_core.domain.decision_requests import RoleAuthority
from yoke_core.domain.inbox_read import inbox_for_actor
from yoke_core.domain.steering_fleet_report_questions import (
    question_lines,
    question_states,
    read_questions,
)
from yoke_core.domain.work_claim_targets import TARGET_KIND_ITEM, encode_scope

LINKED = PROJECT_BETA * 100 + 1
PLAIN = PROJECT_BETA * 100 + 2
CLAIMER = "yoke-worker-claiming-linked"
NAMER = "yoke-worker-naming-linked"
PLAIN_WORKER = "yoke-worker-plain"
HAND = "hand-started-other"


def _item(conn, item_id, version, now):
    conn.execute(
        "INSERT INTO items (id, title, status, priority, created_at, updated_at, "
        "source, project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (%s, 'Work', 'implementing', 'medium', %s, %s, '2', %s, %s, "
        "'dash', %s)",
        (item_id, now, now, PROJECT_BETA, item_id, version),
    )


def _ask(conn, session, item_id=None):
    context = {"question": f"Which way, {session}?", "options": [{"id": "a", "label": "A"}]}
    if item_id is not None:
        context["item_id"] = item_id
    question, _ = file_question(
        conn,
        kind="operator_question",
        subject_type="session_question",
        subject_key=f"{session}:{item_id}",
        requesting_session_id=session,
        session_id=session,
        project_id=PROJECT_BETA,
        originator_actor_id=HUMAN_ACTOR_ID,
        role_authorities=[RoleAuthority("project", PROJECT_BETA, "owner")],
        subject_context=context,
    )
    return question["id"]


def _world(conn):
    seed_standard_steering_world(conn)
    seed_strategy_doc(conn, PROJECT_ALPHA, "RELEASES")
    version = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id = 'dash'"
    ).fetchone()[0]
    now = iso8601_now()
    _item(conn, LINKED, version, now)
    _item(conn, PLAIN, version, now)
    conn.execute(
        "INSERT INTO item_strategy_docs (item_id, project_id, strategy_doc_slug, "
        "linked_at) VALUES (%s, %s, 'RELEASES', %s)",
        (LINKED, PROJECT_ALPHA, now),
    )
    for session in (CLAIMER, NAMER, PLAIN_WORKER, HAND):
        seed_session(conn, session, PROJECT_BETA)
    conn.execute(
        "UPDATE harness_sessions SET launch_origin='yoke' WHERE session_id IN (%s, %s, %s)",
        (CLAIMER, NAMER, PLAIN_WORKER),
    )
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, "
        "last_heartbeat) VALUES (%s, %s, %s, %s, %s)",
        (CLAIMER, TARGET_KIND_ITEM, encode_scope({"item_id": LINKED}), now, now),
    )
    conn.commit()
    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(conn, SESSION_ALPHA, PROJECT_ALPHA)
        acquire_steering(conn, SESSION_BETA, PROJECT_BETA)
    ids = {
        "claimed": _ask(conn, CLAIMER),
        "named": _ask(conn, NAMER, LINKED),
        "plain": _ask(conn, PLAIN_WORKER, PLAIN),
        "hand": _ask(conn, HAND, PLAIN),
        "own": _ask(conn, SESSION_BETA, LINKED),
    }
    conn.commit()
    return ids


def _seen(conn, session):
    return {row.request_id: row.unattended for row in read_questions(conn, session)}


def test_unattended_document_question_waits_with_owning_project_seat(test_db):
    ids = _world(test_db)
    note = "unattended: no live seat for RELEASES"
    assert _seen(test_db, SESSION_ALPHA) == {ids["claimed"]: note, ids["named"]: note}
    assert _seen(test_db, SESSION_BETA) == {ids["plain"]: "", ids["own"]: ""}
    lines = question_lines(read_questions(test_db, SESSION_ALPHA), iso8601_now())
    assert any(f"request {ids['named']} " in line and note in line for line in lines)

    with patch("yoke_core.domain.steering_claims.emit_steering_claimed"):
        acquire_steering(test_db, SESSION_GAMMA, PROJECT_ALPHA, document="RELEASES")
    assert _seen(test_db, SESSION_GAMMA) == {ids["claimed"]: "", ids["named"]: ""}
    assert _seen(test_db, SESSION_ALPHA) == {}
    assert _seen(test_db, SESSION_BETA) == {ids["plain"]: "", ids["own"]: ""}
    assert set(question_states(test_db, SESSION_GAMMA)) == {ids["claimed"], ids["named"]}


def test_other_hand_started_question_never_reaches_a_seat(test_db):
    ids = _world(test_db)
    for session in (SESSION_ALPHA, SESSION_BETA, SESSION_GAMMA):
        assert ids["hand"] not in question_states(test_db, session)
    assert ids["own"] not in question_states(test_db, SESSION_ALPHA)


def test_inbox_still_lists_every_question(test_db):
    ids = _world(test_db)
    waiting = inbox_for_actor(
        test_db, actor_id=HUMAN_ACTOR_ID, project_ids=[PROJECT_BETA], include_read=False
    )
    assert set(ids.values()) <= {row["id"] for row in waiting["needs_decision"]}
