"""A mis-specified item plan attachment can be retracted, not waived.

The attachment is standing and re-materializes on every future run. Waiver
records the wrong fact; supersede needs a passing replacement that cannot
exist when the correct answer is that no post-deploy case belongs. Retract
the attachment, retire what it materialized as retracted, and leave the
item unanswered until it attaches a corrected plan or records no obligation.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    create_smoke_plan,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    QaCasesNotSelectedError,
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers import qa_post_deploy_record_no_obligation as record
from yoke_core.domain.post_deploy_verification_answer import (
    ANSWERED,
    UNANSWERED,
    answer_for_item,
    classify,
)
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

LINEAGE = "f" * 40
RETRACT_REASON = (
    "attached a machine-local CLI probe as standing post-deploy verification"
)


@contextmanager
def _handler_uses(conn):
    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield


def _seed_item(conn, *, item_id: int) -> None:
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="release",
    )
    conn.commit()


def _attach_post_deploy(conn, *, item_id: int, slug: str) -> int:
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    plan_id = create_smoke_plan(conn, project="yoke", slug=slug)
    attach_plan_to_item(
        conn,
        plan_id=int(plan_id),
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    return int(plan_id)


def _materialize_item(conn, *, item_id: int) -> dict:
    from yoke_core.domain.qa_plan_attachments import materialize_for_item

    return materialize_for_item(conn, item_id=item_id, transition_id="release")


def _record_verdict(conn, requirement_id: int, verdict: str) -> None:
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id, performed_by, qa_kind, verdict, "
        "created_at) VALUES (%s,'agent','plan_case',%s,'2026-09-20T00:00:00Z')",
        (int(requirement_id), verdict),
    )
    conn.commit()


def _retract(conn, *, item_id: int, plan_id: int, reason: str = RETRACT_REASON):
    from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item

    return retract_plan_from_item(
        conn,
        item_id=item_id,
        plan_id=int(plan_id),
        transition_id="release",
        reason=reason,
        source="operator",
    )


def _record_no_obligation(item_id: int, reason: str) -> object:
    return record.handle_qa_post_deploy_record_no_obligation(
        FunctionCallRequest(
            function="qa.post_deploy.record_no_obligation",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"reason": reason},
        )
    )


def test_a_retracted_attachment_does_not_answer_the_question() -> None:
    """Classify must ignore a withdrawn attachment, even on a new client.

    An old payload omits ``retracted_at``; treating absence as live keeps
    sessions working until the serving build learns the column.
    """
    retracted = classify(
        attachments=[
            {"qa_phase": "post_deploy", "retracted_at": "2026-09-20T16:00:00Z"}
        ],
        requirements=[],
    )
    live = classify(
        attachments=[{"qa_phase": "post_deploy"}],
        requirements=[],
    )
    retired_case = classify(
        attachments=[],
        requirements=[
            {
                "qa_phase": "post_deploy",
                "qa_kind": "plan_case",
                "waived_at": None,
                "retracted_at": "2026-09-20T16:00:00Z",
            }
        ],
    )

    assert retracted.verdict == UNANSWERED
    assert live.verdict == ANSWERED
    assert retired_case.verdict == UNANSWERED


def test_retracting_the_attachment_stops_it_re_materializing(test_db) -> None:
    item_id = 9851
    _seed_item(test_db, item_id=item_id)
    plan_id = _attach_post_deploy(
        test_db, item_id=item_id, slug="retract-stops-rematerialize"
    )
    first = _materialize_item(test_db, item_id=item_id)
    assert first["created_requirement_ids"]

    result = _retract(test_db, item_id=item_id, plan_id=plan_id)

    row = test_db.execute(
        "SELECT retracted_at, retraction_rationale, retraction_source, "
        "attached_at, plan_id FROM qa_plan_item_attachments "
        "WHERE item_id=%s AND plan_id=%s",
        (item_id, plan_id),
    ).fetchone()
    again = _materialize_item(test_db, item_id=item_id)
    member_plans = test_db.execute(
        "SELECT a.plan_id FROM qa_plan_item_attachments a "
        "WHERE a.item_id=%s AND a.qa_phase='post_deploy'",
        (item_id,),
    ).fetchall()

    assert result["retracted"] is True
    assert row["retracted_at"]
    assert row["retraction_rationale"] == RETRACT_REASON
    assert row["retraction_source"] == "operator"
    assert row["attached_at"]
    assert int(row["plan_id"]) == plan_id
    assert again["created_requirement_ids"] == []
    assert answer_for_item(test_db, item_id).verdict == UNANSWERED
    from yoke_core.domain.qa_deployment_member_attached_plans import (
        attached_member_plan_ids,
    )

    assert attached_member_plan_ids(test_db, member_item_id=item_id) == []
    assert member_plans  # the row remains readable


def test_retracted_requirements_leave_waiver_and_supersession_listings(
    test_db,
) -> None:
    item_id = 9852
    _seed_item(test_db, item_id=item_id)
    plan_id = _attach_post_deploy(
        test_db, item_id=item_id, slug="retract-not-a-waiver"
    )
    created = _materialize_item(test_db, item_id=item_id)["created_requirement_ids"]
    requirement_id = int(created[0])
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s, waiver_rationale=%s, "
        "waiver_source='operator' WHERE id=%s",
        ("2026-09-20T16:05:50Z", "stopgap until retraction exists", requirement_id),
    )
    test_db.commit()

    _retract(test_db, item_id=item_id, plan_id=plan_id)
    with _handler_uses(test_db):
        recorded = _record_no_obligation(item_id, "nothing observable once deployed")

    row = test_db.execute(
        "SELECT waived_at, waiver_rationale, superseded_by_requirement_id, "
        "retracted_at, retraction_rationale FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    waivers = test_db.execute(
        "SELECT id FROM qa_requirements WHERE item_id=%s AND waived_at IS NOT NULL",
        (item_id,),
    ).fetchall()

    assert recorded.primary_success
    assert row["waived_at"] is None
    assert row["waiver_rationale"] is None
    assert row["superseded_by_requirement_id"] is None
    assert row["retracted_at"]
    assert row["retraction_rationale"] == RETRACT_REASON
    assert waivers == []
    assert answer_for_item(test_db, item_id).verdict != ANSWERED


def test_silence_still_blocks_after_retraction(test_db) -> None:
    item_id = 9853
    run_id = "run-pd-retract-silence"
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(item_id,),
        lineage=LINEAGE,
    )
    plan_id = _attach_post_deploy(
        test_db, item_id=item_id, slug="retract-silence-still-blocks"
    )
    _retract(test_db, item_id=item_id, plan_id=plan_id)

    with pytest.raises(QaCasesNotSelectedError):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage=ITEM_QA_STAGE,
            deployment_member_item_id=item_id,
        )


def test_a_failing_verification_case_is_not_retirable_this_way(test_db) -> None:
    """Retraction is about the attachment being wrong, not an unwelcome red.

    A Dash item cannot attach a verification plan through the product
    path without a posture selection, so this plants the standing row
    the retract path would see if someone aimed it at a genuine fail.
    """
    item_id = 9854
    _seed_item(test_db, item_id=item_id)
    plan_id = create_smoke_plan(
        test_db, project="yoke", slug="retract-refuses-verification-fail"
    )
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments("
        "item_id, transition_id, qa_phase, plan_id, attached_at) "
        "VALUES (%s,'reviewing-implementation','verification',%s,"
        "'2026-09-20T00:00:00Z')",
        (item_id, int(plan_id)),
    )
    created = test_db.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,plan_id,workflow_transition_id,created_at) "
        "VALUES (%s,'plan_case','verification','blocking','explicit',%s,"
        "'reviewing-implementation','2026-09-20T00:00:00Z') RETURNING id",
        (item_id, int(plan_id)),
    ).fetchone()
    requirement_id = int(created[0])
    test_db.commit()
    _record_verdict(test_db, requirement_id, "fail")

    with pytest.raises(QaPlanError, match="unwelcome verdict|verification"):
        from yoke_core.domain.qa_plan_attachment_retract import retract_plan_from_item

        retract_plan_from_item(
            test_db,
            item_id=item_id,
            plan_id=int(plan_id),
            transition_id="reviewing-implementation",
            reason="the case went red",
            source="agent",
        )

    row = test_db.execute(
        "SELECT retracted_at, waived_at FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()
    assert row["retracted_at"] is None
    assert row["waived_at"] is None


def test_a_passing_post_deploy_case_is_not_rewritten(test_db) -> None:
    item_id = 9855
    _seed_item(test_db, item_id=item_id)
    plan_id = _attach_post_deploy(
        test_db, item_id=item_id, slug="retract-refuses-accepted-pass"
    )
    created = _materialize_item(test_db, item_id=item_id)["created_requirement_ids"]
    _record_verdict(test_db, int(created[0]), "pass")

    with pytest.raises(QaPlanError, match="settled delivery|passing"):
        _retract(test_db, item_id=item_id, plan_id=plan_id)
