"""A member removed after its run failed stays retired when the run is retried."""

from runtime.api.domain.test_deployment_run_member_removal import (
    ITEM,
    ITEM_QA_STAGE,
    REASON,
    RUN,
    _red_member,
)
from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)
from yoke_core.domain.deployment_run_member_removal import remove_members_on
from yoke_core.domain.qa_deployment_run_settlement import (
    restore_retry_obligations,
    settle_unsuccessful_run,
)


def _retraction(conn, requirement_id):
    return conn.execute(
        "SELECT retracted_at,retraction_rationale,retraction_source "
        "FROM qa_requirements WHERE id=%s",
        (requirement_id,),
    ).fetchone()


def test_retry_after_removal_restores_only_current_obligations(test_db):
    requirement = _red_member(test_db)
    shared = int(
        test_db.execute(
            "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,"
            "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,created_at) "
            "VALUES (%s,%s,NULL,'ac_verification','post_deploy','blocking',"
            "'2026-10-20T00:00:00Z') RETURNING id",
            (RUN, ITEM_QA_STAGE),
        ).fetchone()[0]
    )
    settle_unsuccessful_run(test_db, RUN, reason="runner failed")
    test_db.execute(
        "UPDATE deployment_runs SET status='failed',current_stage=%s WHERE id=%s",
        (f"{ITEM_QA_STAGE}-failed", RUN),
    )
    test_db.commit()
    assert _retraction(test_db, requirement)["retraction_source"] == "deployment_run"

    # The audited write itself; eligibility is the removal command's concern.
    remove_members_on(test_db, RUN, [ITEM], reason=REASON, actor_id=1)
    test_db.commit()
    taken_over = _retraction(test_db, requirement)
    assert taken_over["retraction_source"] == "operator"
    assert taken_over["retraction_rationale"] == REASON

    restore_retry_obligations(test_db, RUN)
    test_db.commit()
    assert _retraction(test_db, requirement)["retracted_at"] is not None
    assert _retraction(test_db, shared)["retracted_at"] is None
    # Only the restored shared row still holds the run.
    (owed,) = unresolved_blocking_qa(test_db, RUN)
    assert str(shared) in owed and str(requirement) not in owed


def test_retry_skips_a_non_member_row_the_failed_run_retired(test_db):
    requirement = _red_member(test_db)
    settle_unsuccessful_run(test_db, RUN, reason="runner failed")
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s", (RUN, ITEM)
    )
    restore_retry_obligations(test_db, RUN)
    test_db.commit()
    assert _retraction(test_db, requirement)["retraction_source"] == "deployment_run"
