"""Stage-only plans close from existing containing proof and drive enrollment."""

import pytest

from runtime.api.domain.test_run_settles_plan_on_other_target import ITEM
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from runtime.api.fixtures.supplemental_credit import plan_pair, clone_run, close_group
from runtime.api.fixtures.carried_release_candidate import (
    git,
    record_landing_receipt,
    serve_repository,
)
from yoke_core.domain.completed_item_delivery import completed_deliveries
from yoke_core.domain.deployment_item_completion_runs import latest_qa_member_run
from yoke_core.domain.deployment_qa_plan_credit import plan_credit_misses
from yoke_core.domain.deployment_qa_source_obligation import unsatisfied_blocking
from yoke_core.domain.deployment_run_completion_preview import completion_preview
from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.no_obligation_member_close_out import satisfied_delivery_member


def test_existing_stage_only_plan_credit_settles_production(
    test_db, tmp_path, monkeypatch
):
    _isolate_status_effects(monkeypatch)
    _, commits = plan_pair(test_db, tmp_path, monkeypatch)
    assert plan_credit_misses(test_db, ITEM) == []
    assert unsatisfied_blocking(test_db, item_id=ITEM, target_status="done").count == 0
    assert satisfied_delivery_member(test_db, item_id=ITEM, run_id="run-prod") is True
    preview = completion_preview(test_db, "run-prod")
    assert not preview.blocked
    assert all(member.state != "blocked" for member in preview.members)
    clone_run(test_db, "run-stage-2", "run-stage", commits["stage2"])
    custody = candidate_custody(test_db, "run-stage-2")
    assert ITEM in custody.held_ids and ITEM not in custody.enrollable
    enroll_carried_members(test_db, "run-stage-2",
        carried_work={"derivation": {"contents_known": True}, "items": []})
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM deployment_run_items WHERE run_id='run-stage-2'"
        ).fetchone()[0]
        == 0
    )
    assert plan_credit_misses(test_db, ITEM) == []
    refusal = cmd_update("run-prod", "status", "succeeded")
    assert refusal is None, refusal
    assert tuple(
        test_db.execute(
            "SELECT status,deployed_to FROM items WHERE id=%s", (ITEM,)
        ).fetchone()
    ) == ("done", "prod")
    assert any(
        run["run_id"] == "run-prod"
        for run in completed_deliveries(test_db, [ITEM])[ITEM]
    )


@pytest.mark.parametrize("candidate", ["stage", "unrelated"])
def test_stranded_plan_enrolls_only_when_candidate_contains_landing(
    test_db,
    tmp_path,
    monkeypatch,
    candidate,
):
    from yoke_core.domain.deployment_run_carried_membership import (
        enroll_carried_members,
    )

    _isolate_status_effects(monkeypatch)
    _, commits = plan_pair(test_db, tmp_path, monkeypatch, proof=False)
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id='run-stage'")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',settling_at=NULL WHERE id='run-prod'"
    )
    clone_run(test_db, "run-stage-new", "run-stage", commits[candidate])
    test_db.commit()
    custody = candidate_custody(test_db, "run-stage-new")
    assert (ITEM in custody.enrollable) is (candidate == "stage")
    enroll_carried_members(
        test_db,
        "run-stage-new",
        carried_work={"derivation": {"contents_known": True}, "items": []},
    )
    rows = test_db.execute(
        "SELECT delivery_intent FROM deployment_run_items WHERE run_id='run-stage-new' AND item_id=%s",
        (ITEM,),
    ).fetchall()
    assert bool(rows) is (candidate == "stage")
    if rows:
        assert (
            rows[0][0] is None
        )  # supplemental admission preserves the existing derived intent
        close_group(test_db, "run-stage-new")
        from yoke_core.domain.deployment_run_other_target_members import (
            close_after_other_target_acceptance,
        )

        result = close_after_other_target_acceptance(
            test_db,
            item_id=ITEM,
            public_ref=f"YOK-{ITEM}",
            run_id="run-stage-new",
        )
        assert result.ok, result.detail
        assert (
            test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[
                0
            ]
            == "done"
        )


def test_failed_stage_proof_enrolls_again_but_production_does_not(
    test_db, tmp_path, monkeypatch
):
    _, commits = plan_pair(test_db, tmp_path, monkeypatch, proof=False)
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded',settling_at=NULL WHERE id='run-prod'"
    )
    clone_run(test_db, "run-stage-2", "run-stage", commits["stage2"])
    assert ITEM in candidate_custody(test_db, "run-stage-2").enrollable
    clone_run(test_db, "run-prod-2", "run-prod", commits["stage2"])
    custody = candidate_custody(test_db, "run-prod-2")
    assert ITEM in custody.held_ids and ITEM not in custody.enrollable
    for run_id in ("run-stage-2", "run-prod-2"):
        enroll_carried_members(test_db, run_id,
            carried_work={"derivation": {"contents_known": True}, "items": []})
    assert [(row[0], row[1]) for row in test_db.execute(
        "SELECT run_id,item_id FROM deployment_run_items WHERE run_id IN ('run-stage-2','run-prod-2')"
    ).fetchall()] == [("run-stage-2", ITEM)]


def test_remerge_withdraws_stage_credit(test_db, tmp_path, monkeypatch):
    _, commits = plan_pair(test_db, tmp_path, monkeypatch)
    repo = commits["repo"]
    git(repo, "checkout", "stage")
    (repo / "stage.txt").write_text("New behavior missing from the tested candidate\n")
    git(repo, "commit", "-am", "New landing")
    record_landing_receipt(
        test_db, ITEM, branch="feature", tip=git(repo, "rev-parse", "HEAD")
    )
    from yoke_core.domain.delivery_evidence_ladder import item_merge_identity

    assert item_merge_identity(test_db, ITEM) == git(repo, "rev-parse", "HEAD")
    assert latest_qa_member_run(test_db, item_id=ITEM, target_env="stage") is None
    assert len(plan_credit_misses(test_db, ITEM)) == 1


def test_unreadable_containment_names_recovery(test_db, tmp_path, monkeypatch):
    from yoke_core.domain.deployment_item_completion_runs import (
        supplemental_run_carries_landing,
        completion_runs,
    )

    plan_pair(test_db, tmp_path, monkeypatch)
    serve_repository(monkeypatch, None)
    run = next(
        r
        for r in completion_runs(test_db, ITEM, include_qa=True)
        if r["id"] == "run-stage"
    )
    verdict = supplemental_run_carries_landing(test_db, run, ITEM)
    assert verdict.state == "undetermined"
    misses = plan_credit_misses(test_db, ITEM)
    assert len(misses) == 1
    assert verdict.reason in misses[0]["recovery"]
    assert verdict.recovery in misses[0]["recovery"]
    from yoke_core.domain.deployment_item_completion_runs import uncredited_supplemental_notice
    notice = uncredited_supplemental_notice(test_db, run_id="run-stage", item_id=ITEM)
    assert verdict.reason in notice and verdict.recovery in notice
    assert latest_qa_member_run(test_db, item_id=ITEM, target_env="stage") is None
