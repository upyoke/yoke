"""The done gate reads the supersede link the freeze refusal prescribes.

A deployment-run case that answered wrongly cannot be corrected in place, so
the product tells its owner to record a corrected case that superseded it.
The deployment stage honours that link. These fix the boundary that did not:
an item's ``done`` gate, which asked the admitted copy only whether it was
waived or had passed, so a case corrected exactly as instructed blocked its
item for good and left a waiver as the only exit.

This converges onto a contract the codebase already has rather than adding a
rule: :func:`qa_obligation_settlement.obligation_settled` is how the stage's
per-case check, the fully-discharged read and intake admission all ask this
same question, and the done gate was the one reader still honouring only
``waived_at``.

Why following the link cannot launder a failure through -- stated here
because this is where a future reader will stand before deciding to
"tighten" it back: :func:`source_obligation_consumed` calls
:func:`stage_acceptance_blockers` on the same subject and target *before* it
asks the admitted copy about its discharge, and
:func:`supersede_requirement` refuses a replacement not bound to the same
run, stage, member and ``execution_target_digest``. The replacement is
therefore inside ``scoped_cases()`` for that subject and is graded on its own
evidence in that earlier call, so one that is not passing leaves blockers and
the gate returns before the link is read at all. The un-superseded failing
copy and the link naming a case that did not pass are pinned below beside the
fix, and the refusal's printed recovery is walked end to end rather than
asserted: a refusal naming fewer exits than the system has is how a correct
action gets ruled out.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    MEMBER_QA_STAGE,
    admitted_copy,
    corrected_sibling,
    deliver_with_failing_admitted_copy,
    execute_member_stage,
    member_stage_acceptance,
    succeed_run,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    POST_DEPLOY_RECOVERY,
    source_obligation_consumed,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
)


def _stage_accepted(conn, run_id: str, item_id: int) -> bool:
    return bool(
        deployment_qa_stage_status(
            conn, run_id=run_id, stage_name=MEMBER_QA_STAGE, member_item_id=item_id
        )["accepted"]
    )


def test_superseded_admitted_copy_is_satisfied_at_done_by_its_replacement(
    test_db,
) -> None:
    item_id = 2340
    run_id = "run-supersede-honoured"
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=True
    )
    assert not member_stage_acceptance(test_db, run_id, item_id).accepted

    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="routes were relative to the bare origin; corrected case passed",
        source="operator",
    )
    assert _stage_accepted(test_db, run_id, item_id)
    succeed_run(test_db, run_id)

    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=intake_id
    )
    # The broken row keeps its failing verdict as history rather than being
    # rewritten into a pass, which is the whole point of superseding it.
    verdict = test_db.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "ORDER BY id DESC LIMIT 1",
        (broken_id,),
    ).fetchone()[0]
    assert str(verdict) == "fail"


def test_unsuperseded_failing_copy_still_holds_done(test_db) -> None:
    item_id = 2341
    run_id = "run-supersede-absent"
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, _broken_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=False
    )
    # Forced past the pipeline's own refusal, so the copy's failing verdict
    # is the only thing left standing between the item and done.
    succeed_run(test_db, run_id)
    assert not member_stage_acceptance(test_db, run_id, item_id).accepted
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=intake_id
    )
    blocked = evaluate(
        item_id=item_id, target_status="done", db_path=str(test_db.info.dsn)
    )
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"


def test_supersession_naming_a_case_that_did_not_pass_does_not_satisfy_done(
    test_db,
) -> None:
    item_id = 2342
    run_id = "run-supersede-unproven"
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=True
    )
    record_case_verdict(test_db, corrected_id, "fail", evidence=False)

    with pytest.raises(QaSupersessionError) as refusal:
        supersede_requirement(
            test_db,
            requirement_id=broken_id,
            superseded_by_requirement_id=corrected_id,
            rationale="the replacement never proved anything",
            source="operator",
        )
    assert "not pass" in str(refusal.value)

    # A link written past that refusal still cannot carry the failure
    # through: the replacement is graded on its own evidence in the same
    # scope, so the stage the done gate consults is not accepted either.
    test_db.execute(
        "UPDATE qa_requirements SET superseded_by_requirement_id=%s,"
        "superseded_at='2026-09-14T00:02:00Z' WHERE id=%s",
        (corrected_id, broken_id),
    )
    test_db.commit()
    succeed_run(test_db, run_id)
    assert not member_stage_acceptance(test_db, run_id, item_id).accepted
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=intake_id
    )


def test_the_recovery_the_done_refusal_prints_actually_clears_the_item(
    test_db,
) -> None:
    """Walk the printed recovery on the exact case that triggered it.

    Asserting the wording would pass while the exit stayed unreachable,
    which is the failure this item exists to correct: the refusal offered a
    waiver or another whole delivery cycle while a third exit existed and
    the stage already honoured it.
    """
    item_id = 2343
    run_id = "run-supersede-recovery"
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=False
    )
    db_path = str(test_db.info.dsn)
    blocked = evaluate(item_id=item_id, target_status="done", db_path=db_path)
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    assert blocked["remediation_hint"] == POST_DEPLOY_RECOVERY
    assert "yoke qa requirement supersede" in blocked["remediation_hint"]

    # Follow it exactly: author the corrected case against the deployed
    # target, run it to a recorded pass, then record the supersession. The
    # broken case is re-run and fails again, which is what actually happens
    # to a case whose defect the candidate cannot satisfy.
    corrected_id = corrected_sibling(test_db, broken_id=broken_id)
    execute_member_stage(
        test_db,
        run_id=run_id,
        item_id=item_id,
        verdicts={broken_id: "fail", corrected_id: "pass"},
    )
    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="corrected case passed against the deployed target",
        source="operator",
    )
    assert _stage_accepted(test_db, run_id, item_id)
    succeed_run(test_db, run_id)

    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=intake_id
    )
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None


def test_superseding_an_admitted_copy_leaves_the_next_release_admitting_it(
    test_db,
) -> None:
    """Evidence for the sibling defect: the correction does not reach intake.

    Supersession is run-local by design -- it discharges one frozen copy and
    leaves the intake row it was frozen from exactly as it was. That row is
    still outstanding, so the next run admits a fresh copy carrying the same
    defective body, and its owner is asked to run the same doomed case. This
    pins the behaviour rather than endorsing it: correcting it belongs to the
    supersede surface, the only place that knows the upstream, and blanking
    the intake row from here would silently drop a real obligation forever.
    """
    item_id = 2344
    _insert_dash(test_db, item_id=item_id, status="release")
    intake_id, broken_id, corrected_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-supersede-first", corrected=True
    )
    supersede_requirement(
        test_db,
        requirement_id=broken_id,
        superseded_by_requirement_id=corrected_id,
        rationale="corrected case passed against the deployed target",
        source="operator",
    )
    succeed_run(test_db, "run-supersede-first")
    broken_config = test_db.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (broken_id,)
    ).fetchone()[0]

    _seed_selected_requirement_run(
        test_db, run_id="run-supersede-next", item_id=item_id,
        requirement_id=intake_id,
    )
    assert intake_id in admissible_post_deploy_requirement_ids(
        test_db, run_id="run-supersede-next", item_id=item_id
    )
    next_copy_id = admitted_copy(
        test_db, run_id="run-supersede-next", item_id=item_id
    )
    next_row = test_db.execute(
        "SELECT plan_case_key,method_config,superseded_by_requirement_id "
        "FROM qa_requirements WHERE id=%s",
        (next_copy_id,),
    ).fetchone()
    assert str(next_row["plan_case_key"]) == admitted_requirement_case_key(intake_id)
    assert next_row["method_config"] == broken_config
    assert next_row["superseded_by_requirement_id"] is None
