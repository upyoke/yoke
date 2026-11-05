"""A recorded no-post-deploy-obligation fact is not a waiver.

``declare-none`` still writes a waived row, and that path still discharges
the stage. Genuine emptiness is a different answer: the owner records that
no obligation ever existed, the stage discharges, and every waiver listing
stays empty.
"""

from __future__ import annotations

from runtime.api.domain.post_deploy_no_obligation_test_support import (
    _handler_uses as _handler_uses,
    _no_obligation_row as _no_obligation_row,
    _record as _record,
    _seed_item as _seed_item,
)


import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    QaCasesNotSelectedError,
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_outcome import OUTCOME_DISCHARGED
from yoke_core.domain.post_deploy_verification_answer import (
    NO_OBLIGATION,
    NO_OBLIGATION_QA_KIND,
    UNANSWERED,
    answer_for_item,
    classify,
)

LINEAGE = "e" * 40


def _member_on_qa_stage(conn, *, run_id: str, item_id: int) -> None:
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(item_id,),
        lineage=LINEAGE,
    )


def _materialize(conn, *, run_id: str, item_id: int):
    return materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )


def test_a_no_obligation_row_is_not_a_live_case_and_not_a_waiver() -> None:
    answer = classify(
        attachments=[],
        requirements=[
            {
                "qa_phase": "post_deploy",
                "qa_kind": NO_OBLIGATION_QA_KIND,
                "waived_at": None,
                "instructions": "internal types only",
            }
        ],
    )

    assert answer.verdict == NO_OBLIGATION
    assert answer.reasons == ("internal types only",)
    assert answer.discharges_without_cases is True


def test_silence_is_still_unanswered() -> None:
    assert classify(attachments=[], requirements=[]).verdict == UNANSWERED


def test_a_never_asked_member_is_still_held(test_db) -> None:
    item_id = 9831
    _member_on_qa_stage(test_db, run_id="run-pd-never-asked", item_id=item_id)

    with pytest.raises(QaCasesNotSelectedError):
        _materialize(test_db, run_id="run-pd-never-asked", item_id=item_id)


def test_a_recorded_no_obligation_satisfies_the_stage_with_no_waiver(
    test_db,
) -> None:
    item_id = 9832
    run_id = "run-pd-no-obligation"
    _member_on_qa_stage(test_db, run_id=run_id, item_id=item_id)
    _no_obligation_row(test_db, item_id, "no runtime surface to observe")

    result = _materialize(test_db, run_id=run_id, item_id=item_id)
    verdict = deployment_qa_stage_status(
        test_db,
        run_id=run_id,
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )
    item_waivers = test_db.execute(
        "SELECT id FROM qa_requirements "
        "WHERE item_id=%s AND waived_at IS NOT NULL",
        (item_id,),
    ).fetchall()
    run_waivers = test_db.execute(
        "SELECT id FROM qa_requirements "
        "WHERE deployment_run_id=%s AND waived_at IS NOT NULL",
        (run_id,),
    ).fetchall()

    assert answer_for_item(test_db, item_id).verdict == NO_OBLIGATION
    assert result["created_requirement_ids"] == []
    assert result["declared_no_post_deploy_verification"] == [
        "no runtime surface to observe"
    ]
    assert verdict["accepted"] is True
    assert verdict["outcome"] == OUTCOME_DISCHARGED
    assert item_waivers == []
    assert run_waivers == []


def test_repeating_the_no_obligation_fact_returns_the_one_already_recorded(
    test_db,
) -> None:
    item_id = 9833
    _seed_item(test_db, item_id=item_id, sequence=833)

    with _handler_uses(test_db):
        first = _record(item_id, "docs only")
        again = _record(item_id, "docs only")

    assert again.result_payload["already_recorded"] is True
    assert (
        again.result_payload["requirement_id"]
        == first.result_payload["requirement_id"]
    )
    row = test_db.execute(
        "SELECT qa_kind,waived_at,waiver_rationale,waiver_source "
        "FROM qa_requirements WHERE id=%s",
        (int(first.result_payload["requirement_id"]),),
    ).fetchone()
    assert row["qa_kind"] == NO_OBLIGATION_QA_KIND
    assert row["waived_at"] is None
    assert row["waiver_rationale"] is None
    assert row["waiver_source"] is None
    assert answer_for_item(test_db, item_id).verdict == NO_OBLIGATION


def test_an_item_with_post_deploy_work_cannot_record_no_obligation(
    test_db,
) -> None:
    item_id = 9834
    _seed_item(test_db, item_id=item_id, sequence=834)
    test_db.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,workflow_transition_id,created_at) "
        "VALUES (%s,'live_acceptance','post_deploy','blocking','explicit',"
        "'release','2026-09-20T00:00:00Z')",
        (item_id,),
    )
    test_db.commit()

    with _handler_uses(test_db):
        outcome = _record(item_id, "changed my mind")

    assert not outcome.primary_success
    assert "already has post-deploy verification" in outcome.error.message
