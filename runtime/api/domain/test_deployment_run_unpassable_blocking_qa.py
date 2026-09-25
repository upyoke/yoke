"""A failed blocking requirement is unpassable only with a merge outside the pin."""

from __future__ import annotations

from runtime.api.fixtures.backlog import (
    insert_deployment_run,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    UNDETERMINED,
    ContainmentVerdict,
)
from yoke_core.domain.deployment_run_unpassable_blocking_qa import (
    diagnose_unpassable_blocking_qa,
)
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.steering_fleet_report_render import report_body


RUN_ID = "run-pin-qa"
PIN = "11c1487ec8543ef47c04458bac85a5645382563b"
FIX = "7ff9dad000000000000000000000000000000001"
ITEM_ID = 8801


def _walk(state: str, reason: str = ""):
    class _Walk:
        def __init__(self, conn, project_id, *, candidate_lineage):
            self.lineage = candidate_lineage
            self.asked: list[str] = []

        def contains(self, commit_sha):
            self.asked.append(commit_sha)
            return ContainmentVerdict(state=state, reason=reason)

    return _Walk


class _ForbiddenWalk:
    def __init__(self, *args, **kwargs):
        raise AssertionError("containment must not run without a recorded merge")

    def contains(self, commit_sha):
        raise AssertionError("containment must not run without a recorded merge")


def _seed_failed_member(conn, *, run_id: str = RUN_ID, item_id: int = ITEM_ID):
    insert_item(conn, id=item_id, title="failed member", status="release")
    insert_deployment_run(
        conn,
        id=run_id,
        status="executing",
        current_stage="item-qa",
        release_lineage=PIN,
    )
    req = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_member_item_id=item_id,
        deployment_stage="item-qa",
        qa_kind="browser",
        qa_phase="post_deploy",
        blocking_mode="blocking",
        requirement_source="flow_derived",
    )
    requirement_id = int(req["id"])
    insert_qa_run(conn, qa_requirement_id=requirement_id, verdict="fail")
    return requirement_id


def _record_fix(conn, item_id: int = ITEM_ID, merge_sha: str = FIX) -> None:
    record_entry(
        conn,
        item_id=item_id,
        branch=f"LANE-{item_id}",
        target="main",
        commit_sha=merge_sha,
        merge_sha=merge_sha,
        settled=True,
    )


def test_a_fail_with_no_recorded_merge_does_not_claim_the_pin_is_unpassable(
    test_db,
) -> None:
    requirement_id = _seed_failed_member(test_db)

    diagnosis = diagnose_unpassable_blocking_qa(
        test_db, run_id=RUN_ID, containment_cls=_ForbiddenWalk
    )

    assert diagnosis.unpassable == ()
    assert diagnosis.unproven == ()
    assert diagnosis.notes() == ()
    assert requirement_id > 0


def test_a_fail_whose_merge_is_in_the_pin_does_not_claim_unpassable(test_db) -> None:
    _seed_failed_member(test_db)
    _record_fix(test_db)

    diagnosis = diagnose_unpassable_blocking_qa(
        test_db, run_id=RUN_ID, containment_cls=_walk(CONTAINED)
    )

    assert diagnosis.unpassable == ()
    assert diagnosis.unproven == ()
    assert "cannot pass against this pin" not in " ".join(diagnosis.notes())


def test_a_fail_whose_merge_is_outside_the_pin_names_superseding(test_db) -> None:
    requirement_id = _seed_failed_member(test_db)
    _record_fix(test_db)

    diagnosis = diagnose_unpassable_blocking_qa(
        test_db, run_id=RUN_ID, containment_cls=_walk(NOT_CONTAINED)
    )

    assert [item.requirement_id for item in diagnosis.unpassable] == [requirement_id]
    assert diagnosis.unpassable[0].merge_sha == FIX
    assert diagnosis.unpassable[0].pin == PIN
    note = diagnosis.unpassable[0].note()
    assert f"#{requirement_id} cannot pass against this pin" in note
    assert FIX in note
    assert PIN in note
    recovery = diagnosis.supersede_recovery(RUN_ID)
    assert f"Supersede {RUN_ID}" in recovery
    assert "Re-drive cannot help" in recovery
    assert "Terminalizing stays an operator action" in recovery


def test_unread_containment_is_named_unproven_not_unpassable(test_db) -> None:
    requirement_id = _seed_failed_member(test_db)
    _record_fix(test_db)

    diagnosis = diagnose_unpassable_blocking_qa(
        test_db,
        run_id=RUN_ID,
        containment_cls=_walk(UNDETERMINED, "containment_source_unavailable"),
    )

    assert diagnosis.unpassable == ()
    assert [item.requirement_id for item in diagnosis.unproven] == [requirement_id]
    note = diagnosis.unproven[0].note()
    assert "is unproven (containment_source_unavailable)" in note
    assert "Do not treat this run as unable to pass" in note
    assert "cannot pass against this pin" not in note


def test_the_report_names_an_unpassable_pin_and_moves_the_fingerprint(
    test_db, monkeypatch
) -> None:
    conn = seed_steering_scope(test_db)
    conn.execute(
        "INSERT INTO deployment_runs"
        "(id,project_id,flow,status,current_stage,release_lineage,created_at,started_at) "
        "VALUES (%s,1,'prod-release','executing','item-qa',%s,%s,%s)",
        (RUN_ID, PIN, "2026-08-26T08:00:00Z", "2026-08-26T08:00:00Z"),
    )
    conn.execute(
        "INSERT INTO qa_requirements"
        "(id,deployment_run_id,deployment_stage,deployment_member_item_id,"
        "qa_kind,qa_phase,blocking_mode,requirement_source,created_at) "
        "VALUES (901,%s,'item-qa',1,'browser','post_deploy','blocking','flow_derived',%s)",
        (RUN_ID, "2026-08-26T08:00:00Z"),
    )
    conn.execute(
        "INSERT INTO qa_runs"
        "(qa_requirement_id,performed_by,qa_kind,verdict,created_at,completed_at) "
        "VALUES (901,'agent','browser','fail',%s,%s)",
        ("2026-08-26T08:00:00Z", "2026-08-26T08:00:00Z"),
    )
    conn.commit()
    before = compose(conn).fingerprint()
    body_before = report_body(compose(conn))
    assert "cannot pass against this pin" not in body_before
    assert "Settle or waive each one; the run finishes automatically" in body_before

    _record_fix(conn, item_id=1)
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_unpassable_blocking_qa.CandidateContainment",
        _walk(NOT_CONTAINED),
    )
    report = compose(conn)
    body = report_body(report)

    assert report.deployment_runs[0].pin_qa.unpassable[0].merge_sha == FIX
    assert "YOK-1 #901 cannot pass against this pin" in body
    assert f"Supersede {RUN_ID} with a run pinned above the remediation" in body
    assert "Settle or waive each one; the run finishes automatically" not in body
    assert report.fingerprint() != before


def test_a_blocked_stage_carries_the_unpassable_pin_on_the_run_answer(
    test_db, monkeypatch
) -> None:
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        ITEM_QA_STAGE,
        record_case_verdict,
        seed_member_qa_case,
    )
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

    member = 9903
    run_id = "run-pin-stage"
    requirement_id = seed_member_qa_case(
        test_db, run_id=run_id, member_item_id=member, lineage=PIN
    )
    record_case_verdict(test_db, requirement_id, "fail", evidence=False)
    _record_fix(test_db, item_id=member)
    monkeypatch.setattr(
        "yoke_core.domain.deployment_run_unpassable_blocking_qa.CandidateContainment",
        _walk(NOT_CONTAINED),
    )

    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=ITEM_QA_STAGE, member_item_id=member
    )

    assert any("cannot pass against this pin" in reason for reason in status["reasons"])
    assert any(f"Supersede {run_id}" in reason for reason in status["reasons"])
    assert all("then re-drive the run" not in reason for reason in status["reasons"])
