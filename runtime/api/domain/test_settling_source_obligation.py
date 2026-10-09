"""Source QA credit must not wait for the run that waits for member close-out."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_done_consumption import _accept_member_qa
from runtime.api.domain.test_done_gate_admitted_copy_multiplicity import _deliver_intake
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import (
    _record_evidence,
)
from runtime.api.fixtures.backlog import insert_qa_run
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)


@pytest.mark.parametrize("status", ("executing", "failed", "cancelled"))
@pytest.mark.parametrize("accepted", (True, False))
def test_settling_requires_accepted_source_qa_and_a_live_run(test_db, status, accepted):
    item_id = 9891
    run_id = "run-source-settlement"
    source_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    if accepted:
        _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    else:
        copy = materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=run_id,
            deployment_stage="member-qa",
            deployment_member_item_id=item_id,
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=copy["created_requirement_ids"][0],
            verdict="fail",
        )
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    mark_settling(test_db, run_id)
    test_db.execute(
        "UPDATE deployment_runs SET status=%s WHERE id=%s", (status, run_id)
    )
    test_db.commit()

    assert source_obligation_consumed(
        test_db,
        item_id=item_id,
        source_requirement_id=source_id,
    ) is (accepted and status == "executing")


def _replace_copy_with_passing_case(conn, *, run_id: str, item_id: int) -> int:
    """Correct the member copy by replacement alone, then re-fail the copy."""
    from yoke_core.domain.qa_requirement_replacement import point_at_replacement

    copy = dict(
        conn.execute(
            "SELECT * FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_member_item_id=%s AND method_id IS NOT NULL",
            (run_id, item_id),
        ).fetchone()
    )
    passing = conn.execute(
        "SELECT raw_result FROM qa_runs WHERE qa_requirement_id=%s AND verdict='pass'",
        (copy["id"],),
    ).fetchone()[0]
    columns = [key for key in copy if key != "id"]
    corrected = {**copy, "plan_case_key": f"{copy['plan_case_key']}@corrected"}
    replacement = int(
        conn.execute(
            f"INSERT INTO qa_requirements({','.join(columns)}) "
            f"VALUES ({','.join(['%s'] * len(columns))}) RETURNING id",
            tuple(corrected[key] for key in columns),
        ).fetchone()[0]
    )
    replacement_run = insert_qa_run(
        conn, qa_requirement_id=replacement, verdict="pass", raw_result=passing
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
        (
            replacement_run["id"],
            "evidence://replacement-case",
            "2026-09-14T00:03:00Z",
        ),
    )
    point_at_replacement(conn, int(copy["id"]), replacement)
    # A later re-run of the replaced copy fails; supersession is never stamped.
    insert_qa_run(conn, qa_requirement_id=int(copy["id"]), verdict="fail")
    conn.commit()
    return int(copy["id"])


@pytest.mark.parametrize("replaced", (True, False))
def test_replaced_failing_copy_settles_the_source(test_db, replaced):
    item_id = 9893
    run_id = "run-source-replaced"
    source_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    if replaced:
        copy_id = _replace_copy_with_passing_case(
            test_db, run_id=run_id, item_id=item_id
        )
        assert (
            test_db.execute(
                "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
                (copy_id,),
            ).fetchone()[0]
            is None
        )
    else:
        insert_qa_run(
            test_db,
            qa_requirement_id=test_db.execute(
                "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
                "AND method_id IS NOT NULL",
                (run_id,),
            ).fetchone()[0],
            verdict="fail",
        )
        test_db.commit()

    assert (
        source_obligation_consumed(
            test_db, item_id=item_id, source_requirement_id=source_id
        )
        is replaced
    )


def test_accepted_source_closes_the_member_before_run_success(test_db, monkeypatch):
    from runtime.api.domain.test_status_transition_preflight import (
        _isolate_status_effects,
    )
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

    _isolate_status_effects(monkeypatch)
    item_id = 9892
    run_id = "run-source-closes"
    source_id = _deliver_intake(test_db, item_id=item_id, run_id=run_id)
    _accept_member_qa(test_db, run_id=run_id, item_id=item_id)
    _record_evidence(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,)
    )
    test_db.commit()

    assert cmd_update(run_id, "status", "succeeded") is None
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=source_id
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "done"
    )
