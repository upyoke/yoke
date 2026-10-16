"""Manual-wake item QA waits for steering, not for its stage to begin.

A member whose open requirement says ``wake_path: manual`` is still waited on
by its stage, but the stage driver leaves its owner unwoken. The steering
report lists the requirement with its evidence, its owner, and the exact wake
command, and the row leaves the list once the owner's run is recorded.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

from runtime.api.domain.test_deployment_qa_stage_dispatch_wake import (
    _WAITING,
    _member,
    _run,
)
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.steering_fleet_test_helpers import (
    WORKER_SESSION,
    compose,
    seed_steering_scope,
)
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_qa_manual_wake import (
    NO_OWNER,
    member_holds_for_manual_wake,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_render import report_body
from yoke_core.domain.work_claim_targets import make_item_target

EVIDENCE = "a deployment run with at least 44 members exists after this release"


def _requirement(
    conn: Any,
    *,
    requirement_id: int,
    run_id: str,
    member: int,
    wake_path: str | None,
    stage: str = "item-qa",
) -> None:
    conn.execute(
        "INSERT INTO qa_requirements(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,method_id,plan_case_key,wake_path,wake_evidence,"
        "created_at) VALUES (%s,%s,%s,%s,'plan_case','post_deploy','blocking',"
        "'flow_derived','exploratory-mission','real-traffic',%s,%s,%s)",
        (
            requirement_id,
            run_id,
            stage,
            member,
            wake_path,
            EVIDENCE if wake_path == "manual" else None,
            iso8601_now(),
        ),
    )
    conn.commit()


def _record_run(conn: Any, requirement_id: int, verdict: str = "pass") -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "created_at,completed_at,started_at) VALUES (%s,'agent','plan_case',%s,%s,%s,%s)",
        (requirement_id, verdict, now, now, now),
    )
    conn.commit()


def _drive(conn: Any, run_id: str) -> tuple[int, str, mock.Mock]:
    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=_WAITING,
        ),
        mock.patch.object(
            dispatch_mod, "notify_item_scoped_qa_wait", return_value="delivered"
        ) as notify,
    ):
        rc, diag = materialize_and_gate_deployment_qa_stage(
            conn, {"name": "item-qa", "scope": "item"}, run_id=run_id
        )
    return rc, diag, notify


def test_stage_entry_does_not_wake_an_owner_holding_a_manual_case(
    test_db: Any, capsys: Any
) -> None:
    _run(test_db, "run-manual-1")
    _member(test_db, "run-manual-1", 9701)
    _requirement(
        test_db,
        requirement_id=97011,
        run_id="run-manual-1",
        member=9701,
        wake_path="manual",
    )

    rc, diag, notify = _drive(test_db, "run-manual-1")

    assert rc == -4, "the manual case still blocks the stage"
    assert "awaiting agent verdict" in diag
    notify.assert_not_called()
    assert (
        "holding for manual wake; steering wakes its owner" in capsys.readouterr().out
    )


def test_automatic_and_settled_manual_cases_wake_the_owner_normally(
    test_db: Any,
) -> None:
    _run(test_db, "run-manual-2")
    _member(test_db, "run-manual-2", 9702)
    _member(test_db, "run-manual-2", 9703)
    _requirement(
        test_db,
        requirement_id=97021,
        run_id="run-manual-2",
        member=9702,
        wake_path=None,
    )
    _requirement(
        test_db,
        requirement_id=97031,
        run_id="run-manual-2",
        member=9703,
        wake_path="manual",
    )
    # Steering woke the owner and its run is recorded: no longer held.
    _record_run(test_db, 97031, verdict="fail")

    _rc, _diag, notify = _drive(test_db, "run-manual-2")

    woken = sorted(call.kwargs["item_id"] for call in notify.call_args_list)
    assert woken == [9702, 9703]


def test_waived_or_other_stage_manual_cases_do_not_hold(test_db: Any) -> None:
    _run(test_db, "run-manual-3")
    _member(test_db, "run-manual-3", 9704)
    _requirement(
        test_db,
        requirement_id=97041,
        run_id="run-manual-3",
        member=9704,
        wake_path="manual",
        stage="other-qa",
    )
    _requirement(
        test_db,
        requirement_id=97042,
        run_id="run-manual-3",
        member=9704,
        wake_path="manual",
    )
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s WHERE id=97042", (iso8601_now(),)
    )
    test_db.commit()

    assert not member_holds_for_manual_wake(
        test_db, run_id="run-manual-3", stage_name="item-qa", member_item_id=9704
    )


RUN_ID = "run-20261016-905"
MEMBER = 3467


def _report_run(test_db: Any) -> Any:
    conn = seed_steering_scope(test_db)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN_ID,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(MEMBER,),
        lineage="d" * 40,
    )
    release_seeded_driver(conn, RUN_ID)
    _requirement(
        conn,
        requirement_id=9801,
        run_id=RUN_ID,
        member=MEMBER,
        wake_path="manual",
        stage=ITEM_QA_STAGE,
    )
    return conn


def test_report_lists_the_manual_wake_with_evidence_owner_and_command(
    test_db: Any,
) -> None:
    conn = _report_run(test_db)
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at,"
        "last_heartbeat) VALUES (%s,'item',%s,%s,%s)",
        (
            WORKER_SESSION,
            make_item_target(MEMBER).scope_json(),
            iso8601_now(),
            iso8601_now(),
        ),
    )
    conn.commit()
    ref = render_item_ref(conn, MEMBER)

    report = compose(conn, now=iso8601_now())
    run = report.deployment_runs[0]
    body = report_body(report)

    (wake,) = run.manual_wakes
    assert (wake.requirement_id, wake.item_ref, wake.wake_evidence) == (
        9801,
        ref,
        EVIDENCE,
    )
    assert wake.owner_session_id == WORKER_SESSION
    assert "waiting on manual wake" in body
    assert f"{RUN_ID}  {ref}  requirement #9801 case real-traffic" in body
    assert f"evidence: {EVIDENCE}" in body
    assert f"| yoke say --stdin --item {ref}" in wake.wake_command()
    assert (
        f"yoke qa plan run --deployment-run-id {RUN_ID} --stage {ITEM_QA_STAGE} "
        f"--member {ref} --project yoke"
    ) in wake.wake_command()
    assert f"member {ref}: " in body and "held for manual wake" in body
    projected = report_dict(report)
    assert "9801" in str(projected) and "wake_command" in str(projected)


def test_report_row_names_a_missing_owner_and_leaves_once_run(test_db: Any) -> None:
    conn = _report_run(test_db)

    (wake,) = compose(conn, now=iso8601_now()).deployment_runs[0].manual_wakes
    assert wake.owner() == NO_OWNER

    _record_run(conn, 9801)
    assert compose(conn, now=iso8601_now()).deployment_runs[0].manual_wakes == ()
