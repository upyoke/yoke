"""Operator waiver recording uses a covering seat or the requirement's run lock."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    seed_project,
    seed_session,
    seed_strategy_doc,
)
from yoke_core.domain.db_helpers import iso8601_now
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    seed_member_qa_case,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import acquire as acquire_lock
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.qa_requirement_waive import handle_qa_requirement_waive
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.steering_claims import acquire as acquire_seat
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_registry import lookup

MEMBER = 9801
RECORDER = "waiver-recorder"
WORKER = "member-worker"
RATIONALE = "operator accepted the release without this case"


class _BorrowedConnection:
    """Let production helpers share the test connection without closing it."""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def close(self):
        pass


@pytest.fixture
def waiver_world(test_db):
    requirement_id = seed_member_qa_case(
        test_db, run_id="run-member-waiver", member_item_id=MEMBER
    )
    test_db.execute("UPDATE items SET status='release' WHERE id=%s", (MEMBER,))
    test_db.commit()
    seed_session(test_db, RECORDER, 1)
    seed_session(test_db, WORKER, 1)
    claim = claim_work(test_db, session_id=WORKER, item_id=str(MEMBER))
    with patch(
        "yoke_core.domain.db_helpers.connect",
        side_effect=lambda *a, **k: _BorrowedConnection(test_db),
    ):
        yield test_db, requirement_id, claim


def _request(requirement_id, *, source="operator", function="qa.requirement.waive"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="2", session_id=RECORDER),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={"rationale": RATIONALE, "source": source, "force": True},
    )


def _gate(request):
    register_all_handlers()
    return verify_claim(lookup(request.function), request)


@pytest.mark.parametrize("authority", ["steering", "deploy_lock"])
def test_operator_waiver_keeps_worker_claim_and_settles_run_stage(
    waiver_world, authority
):
    conn, requirement_id, worker_claim = waiver_world
    if authority == "steering":
        acquire_seat(conn, session_id=RECORDER, project_id=1, reason="drive release")
    else:
        acquire_lock(conn, make_deploy_serialization_target(1, "yoke"), RECORDER)
    request = _request(requirement_id)
    assert _gate(request) is None
    with patch(
        "yoke_core.domain.qa_requirement_ops.emit_qa_requirement_event"
    ) as event:
        outcome = handle_qa_requirement_waive(request)
    assert outcome.primary_success
    row = conn.execute(
        "SELECT waived_at,waiver_rationale,waiver_source FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert row[0] is not None
    assert tuple(row)[1:] == (RATIONALE, "operator")
    assert event.call_args.kwargs["event_name"] == "QARequirementWaived"
    assert event.call_args.kwargs["rationale"] == RATIONALE
    assert event.call_args.kwargs["source"] == "operator"
    held = conn.execute(
        "SELECT session_id,released_at FROM work_claims WHERE id=%s",
        (worker_claim["id"],),
    ).fetchone()
    assert tuple(held) == (WORKER, None)
    # The same dispatch the driver re-runs now accepts the discharged subject.
    with patch("yoke_core.domain.deployment_qa_stage_dispatch.report_stage_result"):
        subject = deployment_qa_stage_subject(
            conn,
            run_id="run-member-waiver",
            stage_name=ITEM_QA_STAGE,
            member_item_id=MEMBER,
        )
        code, output = materialize_and_gate_deployment_qa_stage(
            conn, subject["stage"], run_id="run-member-waiver"
        )
    assert code == 0, output


@pytest.mark.parametrize(
    "authority", ["none", "other_seat", "other_lock", "released_seat"]
)
def test_uncovered_recorder_is_refused_with_recovery(waiver_world, authority):
    conn, requirement_id, _ = waiver_world
    if authority in {"other_seat", "released_seat"}:
        seat = acquire_seat(
            conn, session_id=RECORDER, project_id=1, reason="steer items"
        )
        if authority == "other_seat":
            seed_strategy_doc(conn, 1, "AREA-PLAN")
            conn.execute(
                "INSERT INTO item_strategy_docs(item_id,project_id,strategy_doc_slug,linked_at) "
                "VALUES (%s,1,'AREA-PLAN',%s)",
                (MEMBER, iso8601_now()),
            )
        else:
            conn.execute(
                "UPDATE work_claims SET released_at=%s WHERE id=%s",
                ("2026-10-01T00:00:00Z", seat["id"]),
            )
        conn.commit()
    elif authority == "other_lock":
        seed_project(conn, PROJECT_ALPHA, "other")
        acquire_lock(
            conn, make_deploy_serialization_target(PROJECT_ALPHA, "other"), RECORDER
        )
    refusal = _gate(_request(requirement_id))
    assert refusal.error.code == "claim_required"
    assert "ask that holder" in refusal.error.message
    assert (
        conn.execute(
            "SELECT waived_at FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()[0]
        is None
    )


@pytest.mark.parametrize(
    "source,function",
    [
        ("agent", "qa.requirement.waive"),
        ("operator", "qa.requirement.update"),
    ],
)
def test_seat_does_not_bypass_other_qa_claim_checks(waiver_world, source, function):
    conn, requirement_id, _ = waiver_world
    acquire_seat(conn, session_id=RECORDER, project_id=1, reason="steer items")
    refusal = _gate(_request(requirement_id, source=source, function=function))
    assert refusal.error.code == "claim_required"


def test_deploy_lock_does_not_cover_item_requirement_outside_a_run(waiver_world):
    conn, requirement_id, _ = waiver_world
    conn.execute(
        "UPDATE qa_requirements SET item_id=%s,deployment_run_id=NULL,"
        "deployment_stage=NULL,deployment_member_item_id=NULL WHERE id=%s",
        (MEMBER, requirement_id),
    )
    conn.commit()
    acquire_lock(conn, make_deploy_serialization_target(1, "yoke"), RECORDER)
    assert _gate(_request(requirement_id)).error.code == "claim_required"


def test_ended_steering_session_grants_no_authority(waiver_world):
    conn, requirement_id, _ = waiver_world
    acquire_seat(conn, session_id=RECORDER, project_id=1, reason="steer items")
    conn.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        ("2026-10-01T00:00:00Z", RECORDER),
    )
    conn.commit()
    assert _gate(_request(requirement_id)).error.code == "claim_required"


def test_document_seat_covers_its_linked_member(waiver_world):
    conn, requirement_id, _ = waiver_world
    seed_strategy_doc(conn, 1, "AREA-PLAN")
    conn.execute(
        "INSERT INTO item_strategy_docs(item_id,project_id,strategy_doc_slug,linked_at) "
        "VALUES (%s,1,'AREA-PLAN',%s)",
        (MEMBER, iso8601_now()),
    )
    conn.commit()
    acquire_seat(
        conn,
        session_id=RECORDER,
        project_id=1,
        document="AREA-PLAN",
        reason="steer area",
    )
    assert _gate(_request(requirement_id)) is None
