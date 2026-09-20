"""The post-deploy verification question: its answers, and who honours them.

An item used to reach its deployment QA stage having never been asked what
it wanted checked once the code was live, and the stage refused it there --
with production already serving the candidate that check was for. Moving the
question earlier needs two things that live here: an answer an item can
record when it genuinely has nothing to verify, and a stage that can tell
that recorded answer from a member nobody ever asked.

The asking surface itself is the merge gate, covered in
``test_qa_item_stage_plan_gate``.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

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
from yoke_core.domain.handlers import qa_post_deploy_declare_none as declare
from yoke_core.domain.post_deploy_verification_answer import (
    ANSWERED,
    DECLARATION_QA_KIND,
    DECLARED_NONE,
    UNANSWERED,
    answer_for_item,
    classify,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

LINEAGE = "e" * 40


@contextmanager
def _handler_uses(conn):
    """Point the handler's own ``connect()`` at the test connection."""

    class _Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            return None

    with patch("yoke_core.domain.db_helpers.connect", return_value=_Borrowed()):
        yield


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


def _declaration_row(conn, item_id: int, reason: str) -> int:
    """The artifact ``declare-none`` writes, as the stage will read it."""
    requirement_id = int(
        conn.execute(
            "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
            "requirement_source,instructions,workflow_transition_id,waived_at,"
            "waiver_rationale,waiver_source,created_at) "
            "VALUES (%s,%s,'post_deploy','non_blocking','explicit',%s,'release',"
            "'2026-09-20T00:00:00Z',%s,'agent','2026-09-20T00:00:00Z') "
            "RETURNING id",
            (int(item_id), DECLARATION_QA_KIND, reason, reason),
        ).fetchone()[0]
    )
    conn.commit()
    return requirement_id


def _seed_item(conn, *, item_id: int, sequence: int):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        conn,
        id=item_id,
        project_sequence=sequence,
        workflow_id="dash",
        status="release",
    )
    conn.commit()


# --- classification ---------------------------------------------------------


def test_an_item_with_no_post_deploy_record_has_answered_nothing() -> None:
    assert classify(attachments=[], requirements=[]).verdict == UNANSWERED


def test_a_waived_post_deploy_row_reads_as_a_recorded_declaration() -> None:
    answer = classify(
        attachments=[],
        requirements=[
            {
                "qa_phase": "post_deploy",
                "waived_at": "2026-09-20T00:00:00Z",
                "waiver_rationale": "no runtime surface changes",
            }
        ],
    )

    assert answer.verdict == DECLARED_NONE
    assert answer.reasons == ("no runtime surface changes",)


def test_a_live_post_deploy_obligation_reads_as_answered() -> None:
    answer = classify(
        attachments=[],
        requirements=[{"qa_phase": "post_deploy", "waived_at": None}],
    )

    assert answer.verdict == ANSWERED


def test_a_superseded_row_is_answered_rather_than_declared_none() -> None:
    """Supersession hands the obligation on; it does not decline one."""
    answer = classify(
        attachments=[],
        requirements=[
            {
                "qa_phase": "post_deploy",
                "waived_at": None,
                "superseded_by_requirement_id": 41,
            }
        ],
    )

    assert answer.verdict == ANSWERED


def test_a_verification_phase_row_does_not_answer_the_deploy_question() -> None:
    answer = classify(
        attachments=[{"qa_phase": "verification"}],
        requirements=[{"qa_phase": "verification", "waived_at": None}],
    )

    assert answer.verdict == UNANSWERED


# --- the deployment QA stage ------------------------------------------------


def test_a_member_that_never_answered_is_still_held(test_db) -> None:
    item_id = 9811
    _member_on_qa_stage(test_db, run_id="run-pd-unanswered", item_id=item_id)

    with pytest.raises(QaCasesNotSelectedError):
        _materialize(test_db, run_id="run-pd-unanswered", item_id=item_id)


def test_the_stage_refusal_names_the_answers_that_belong_to_the_item(
    test_db,
) -> None:
    item_id = 9812
    _member_on_qa_stage(test_db, run_id="run-pd-refusal-text", item_id=item_id)

    with pytest.raises(QaCasesNotSelectedError) as refusal:
        _materialize(test_db, run_id="run-pd-refusal-text", item_id=item_id)

    message = str(refusal.value)
    # The run-scoped recovery, which is all this surface can offer now.
    assert "yoke qa plan run" in message
    # And where the durable answers were supposed to be given instead.
    assert "qa post-deploy declare-none" in message
    assert "qa item-plan attach" in message
    assert "before it merges" in message


def test_a_recorded_declaration_passes_the_stage_with_no_plan(test_db) -> None:
    item_id = 9813
    _member_on_qa_stage(test_db, run_id="run-pd-declared", item_id=item_id)
    _declaration_row(test_db, item_id, "ships no runtime surface to check")

    result = _materialize(test_db, run_id="run-pd-declared", item_id=item_id)
    verdict = deployment_qa_stage_status(
        test_db,
        run_id="run-pd-declared",
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )

    assert result["created_requirement_ids"] == []
    assert result["declared_no_post_deploy_verification"] == [
        "ships no runtime surface to check"
    ]
    assert verdict["accepted"] is True
    # A discharge, never a pass: nothing ran, and the result says so.
    assert verdict["outcome"] == OUTCOME_DISCHARGED


def test_a_member_nobody_asked_does_not_pass_on_an_empty_case_set(
    test_db,
) -> None:
    """Silence is not a declaration, and an empty case set is still a wait."""
    item_id = 9815
    _member_on_qa_stage(test_db, run_id="run-pd-silent", item_id=item_id)

    verdict = deployment_qa_stage_status(
        test_db,
        run_id="run-pd-silent",
        stage_name=ITEM_QA_STAGE,
        member_item_id=item_id,
    )

    assert verdict["accepted"] is False


def test_the_declaration_credits_no_manufactured_case(test_db) -> None:
    """Passing the stage must not invent an obligation to pass it with."""
    item_id = 9814
    _member_on_qa_stage(test_db, run_id="run-pd-no-manufacture", item_id=item_id)
    _declaration_row(test_db, item_id, "documentation only")

    _materialize(test_db, run_id="run-pd-no-manufacture", item_id=item_id)

    rows = test_db.execute(
        "SELECT count(*) FROM qa_requirements WHERE deployment_run_id=%s",
        ("run-pd-no-manufacture",),
    ).fetchone()
    assert int(rows[0]) == 0


# --- the declaration surface ------------------------------------------------


def _declare(item_id: int, reason: str) -> object:
    return declare.handle_qa_post_deploy_declare_none(
        FunctionCallRequest(
            function="qa.post_deploy.declare_none",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"reason": reason},
        )
    )


def test_declare_none_records_a_waived_post_deploy_row(test_db) -> None:
    item_id = 9821
    _seed_item(test_db, item_id=item_id, sequence=821)

    with _handler_uses(test_db):
        outcome = _declare(item_id, "no user-visible surface after deploy")

    assert outcome.primary_success
    row = test_db.execute(
        "SELECT qa_kind,qa_phase,waived_at,waiver_rationale,blocking_mode "
        "FROM qa_requirements WHERE id=%s",
        (int(outcome.result_payload["requirement_id"]),),
    ).fetchone()
    assert row["qa_kind"] == DECLARATION_QA_KIND
    assert row["qa_phase"] == "post_deploy"
    assert row["waived_at"]
    assert row["waiver_rationale"] == "no user-visible surface after deploy"
    # Non-blocking: a declaration answers the question, it does not open one.
    assert row["blocking_mode"] == "non_blocking"
    assert answer_for_item(test_db, item_id).verdict == DECLARED_NONE


def test_repeating_the_declaration_returns_the_one_already_recorded(
    test_db,
) -> None:
    item_id = 9822
    _seed_item(test_db, item_id=item_id, sequence=822)

    with _handler_uses(test_db):
        first = _declare(item_id, "internal refactor only")
        again = _declare(item_id, "internal refactor only")

    assert again.result_payload["already_declared"] is True
    assert (
        again.result_payload["requirement_id"]
        == first.result_payload["requirement_id"]
    )


def test_an_item_with_post_deploy_work_cannot_declare_it_has_none(test_db) -> None:
    item_id = 9823
    _seed_item(test_db, item_id=item_id, sequence=823)
    test_db.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,workflow_transition_id,created_at) "
        "VALUES (%s,'live_acceptance','post_deploy','blocking','explicit','release',"
        "'2026-09-20T00:00:00Z')",
        (item_id,),
    )
    test_db.commit()

    with _handler_uses(test_db):
        outcome = _declare(item_id, "changed my mind")

    assert not outcome.primary_success
    assert "already has post-deploy verification" in outcome.error.message
