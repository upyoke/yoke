"""Operator QA repairs retain worker claims and record their covering seat."""

from unittest.mock import patch

import pytest

from runtime.api.domain.steering_claim_test_support import (
    seed_session,
    seed_strategy_doc,
)
from runtime.api.domain.test_qa_operator_waiver_authority import _BorrowedConnection
from runtime.api.domain.test_qa_requirement_successor import chain, inconsistent
from runtime.api.fixtures.qa_declared_replacement_fixture import requirement_row
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.qa_requirement_supersede import (
    handle_qa_requirement_supersede,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_claims import acquire
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_registry import lookup

RECORDER = "repair-recorder"
WORKER = "repair-worker"
MEMBER = 9811


@pytest.fixture
def repair_world(test_db):
    old, middle, final = chain(test_db)
    inconsistent(test_db, old, final)
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (MEMBER,))
    test_db.commit()
    seed_session(test_db, RECORDER, 1)
    seed_session(test_db, WORKER, 1)
    claim = claim_work(test_db, session_id=WORKER, item_id=str(MEMBER))
    with patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=lambda *a, **k: _BorrowedConnection(test_db),
    ):
        yield test_db, old, final, claim


def request(old, final, *, session=RECORDER, source="operator", reconcile=True):
    return FunctionCallRequest(
        function="qa.requirement.supersede",
        actor={"actor_id": "2", "session_id": session},
        target={"kind": "qa_requirement", "qa_requirement_id": old},
        payload={
            "superseded_by_requirement_id": final,
            "source": source,
            "reconcile": reconcile,
            "rationale": "unique terminal confirmed",
        },
    )


def gate(req):
    register_all_handlers()
    return verify_claim(lookup(req.function), req)


@pytest.mark.parametrize("authority", ["steering", "document"])
def test_repair_without_item_claim_records_authority_and_notifies_holder(
    repair_world, authority
):
    conn, old, final, claim = repair_world
    document = None
    if authority == "document":
        document = "AREA-PLAN"
        seed_strategy_doc(conn, 1, document)
        conn.execute(
            "INSERT INTO item_strategy_docs(item_id,project_id,strategy_doc_slug,linked_at) VALUES (%s,1,%s,%s)",
            (MEMBER, document, iso8601_now()),
        )
        conn.commit()
    seat = acquire(
        conn,
        session_id=RECORDER,
        project_id=1,
        document=document,
        reason="repair QA",
    )
    req = request(old, final)
    assert gate(req) is None
    with patch(
        "yoke_core.domain.deployment_run_driver_notice.push_member_notice",
        return_value="undelivered",
    ) as notice:
        outcome = handle_qa_requirement_supersede(req)
    assert outcome.primary_success, outcome
    row = requirement_row(conn, old)
    assert (
        row["replacement_requirement_id"]
        == row["superseded_by_requirement_id"]
        == final
    )
    assert f"session={RECORDER}" in row["supersession_rationale"]
    assert f"'claim_id': {seat['id']}" in row["supersession_rationale"]
    assert "'scope':" in row["supersession_rationale"]
    assert notice.call_args.kwargs["item_id"] == MEMBER
    assert RECORDER in notice.call_args.kwargs["body_for_route"]("holder")
    assert outcome.result_payload["repair_notice"]["delivery"] == "undelivered"
    held = conn.execute(
        "SELECT session_id,released_at FROM work_claims WHERE id=%s", (claim["id"],)
    ).fetchone()
    assert tuple(held) == (WORKER, None)


@pytest.mark.parametrize(
    "authority",
    [
        "none",
        "worker",
        "released",
        "ended",
        "terminated",
        "other_document",
    ],
)
def test_unauthorized_repair_refuses_even_with_item_claim(repair_world, authority):
    conn, old, final, _ = repair_world
    session = WORKER if authority == "worker" else RECORDER
    if authority not in {"none", "worker"}:
        seat = acquire(conn, session_id=RECORDER, project_id=1, reason="repair QA")
        if authority == "released":
            conn.execute(
                "UPDATE work_claims SET released_at=%s WHERE id=%s",
                (iso8601_now(), seat["id"]),
            )
        elif authority in {"ended", "terminated"}:
            column = "ended_at" if authority == "ended" else "terminated_at"
            conn.execute(
                f"UPDATE harness_sessions SET {column}=%s WHERE session_id=%s",
                (iso8601_now(), RECORDER),
            )
        elif authority == "other_document":
            seed_strategy_doc(conn, 1, "AREA-PLAN")
            conn.execute(
                "INSERT INTO item_strategy_docs(item_id,project_id,strategy_doc_slug,linked_at) VALUES (%s,1,'AREA-PLAN',%s)",
                (MEMBER, iso8601_now()),
            )
        conn.commit()
    req = request(old, final, session=session)
    before = requirement_row(conn, old)
    refusal = gate(req)
    assert refusal.error.code == "QA_RECONCILIATION_AUTHORITY_REQUIRED"
    assert "requires a live steering seat" in refusal.error.message
    assert "yoke say --steering" in refusal.error.message
    assert not handle_qa_requirement_supersede(req).primary_success
    assert requirement_row(conn, old) == before


def test_agent_supersession_keeps_ordinary_claim_policy(repair_world):
    conn, old, final, _ = repair_world
    acquire(conn, session_id=RECORDER, project_id=1, reason="repair QA")
    assert (
        gate(request(old, final, source="agent", reconcile=False)).error.code
        == "claim_required"
    )
    assert (
        gate(request(old, final, session=WORKER, source="agent", reconcile=False))
        is None
    )


def test_ordinary_operator_supersession_keeps_its_claim_policy(repair_world):
    conn, old, final, _ = repair_world
    acquire(conn, session_id=RECORDER, project_id=1, reason="repair QA")
    assert gate(request(old, final, reconcile=False)).error.code == "claim_required"


def test_notice_failure_reports_durable_repair_and_recovery(repair_world):
    conn, old, final, _ = repair_world
    acquire(conn, session_id=RECORDER, project_id=1, reason="repair QA")
    with patch(
        "yoke_core.domain.deployment_run_driver_notice.push_member_notice",
        side_effect=RuntimeError("notice unavailable"),
    ):
        outcome = handle_qa_requirement_supersede(request(old, final))
    assert outcome.primary_success
    assert requirement_row(conn, old)["replacement_requirement_id"] == final
    assert outcome.result_payload["repair_notice"]["delivery"] == "failed"
    assert (
        "QA_REPAIR_NOTICE_FAILED" in outcome.result_payload["repair_notice"]["recovery"]
    )
