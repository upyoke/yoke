"""An independent red member and a later correction do not deadlock delivery."""

import pytest

from runtime.api.domain.test_deployment_run_auto_completion import _held_lock

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    record_case_verdict,
    seed_member_qa_case,
)
from runtime.api.fixtures.carried_release_candidate import (
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_no_obligation_member_close_out import (
    _ready_member,
    _no_obligation,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _executing_run,
    _claim_held,
)
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)
from yoke_core.domain.deployment_run_membership_removals import membership_removals
from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_run_acceptance import pinned_stages
from yoke_core.domain.deployment_runs_crud_mutate import cmd_remove_item, cmd_update

ITEM = 9961
RUN = "run-remove-red"
REASON = "red member will ride the next release"


def _red_member(conn):
    requirement = seed_member_qa_case(conn, run_id=RUN, member_item_id=ITEM)
    conn.execute("UPDATE items SET status='release' WHERE id=%s", (ITEM,))
    conn.commit()
    record_case_verdict(conn, requirement, "fail", evidence=True)
    return requirement


def _still_member(conn):
    return (
        conn.execute(
            "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, ITEM),
        ).fetchone()
        is not None
    )


@pytest.mark.parametrize("failed", [False, True])
def test_red_member_removal_retracts_only_its_outstanding_run_qa(
    test_db, monkeypatch, failed
):
    requirement = _red_member(test_db)
    if failed:
        test_db.execute(
            "UPDATE deployment_runs SET status='failed',current_stage=%s WHERE id=%s",
            (f"{ITEM_QA_STAGE}-failed", RUN),
        )
        test_db.commit()
    assert unresolved_blocking_qa(test_db, RUN)
    assert (
        qa_stage_outstanding(test_db, run_id=RUN, stage_name=ITEM_QA_STAGE).waiting == 1
    )
    _held_lock(monkeypatch)
    message = cmd_remove_item(
        RUN, ITEM, reason=REASON, session_id="remover", actor_id=2
    )
    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()["status"] == ("failed" if failed else "succeeded")
    if failed:
        assert f"-- {RUN} --from-stage {ITEM_QA_STAGE}" in message
    assert "a later release enrolls it" in message
    assert not _still_member(test_db)
    row = test_db.execute(
        "SELECT retracted_at,retraction_rationale,waived_at FROM qa_requirements WHERE id=%s",
        (requirement,),
    ).fetchone()
    assert row["retracted_at"] and row["retraction_rationale"] == REASON
    assert row["waived_at"] is None
    assert unresolved_blocking_qa(test_db, RUN) == []
    assert (
        qa_stage_outstanding(test_db, run_id=RUN, stage_name=ITEM_QA_STAGE).waiting == 0
    )
    stage = pinned_stages(test_db, RUN)[-1]
    assert materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN) == (
        0,
        "",
    )
    (removal,) = membership_removals(test_db, RUN)
    assert removal["item_id"] == ITEM and removal["reason"] == REASON
    assert removal["session_id"] == "remover" and removal["actor_id"] == 2
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[
            "status"
        ]
        == "release"
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ("current_stage='deploy'", "not at an item-scoped"),
        ("status='succeeded'", "only while status='created'"),
        ("status='failed',current_stage='deploy-failed'", "only at item-qa-failed"),
        ("status='failed',current_stage='item-qa'", "only at item-qa-failed"),
        ("settling_at='2026-09-30T00:00:00Z'", "not at an item-scoped"),
    ],
)
def test_other_run_boundaries_refuse_removal(test_db, change, reason):
    requirement = _red_member(test_db)
    test_db.execute(f"UPDATE deployment_runs SET {change} WHERE id=%s", (RUN,))
    test_db.commit()
    with pytest.raises(ValueError, match=reason):
        cmd_remove_item(RUN, ITEM, reason=REASON)
    assert _still_member(test_db)
    assert not test_db.execute(
        "SELECT retracted_at FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()["retracted_at"]
    assert not membership_removals(test_db, RUN)


def test_run_scoped_qa_refuses_removal(test_db):
    _red_member(test_db)
    # Edit the fixture's pinned definition solely to stand at the shared stage.
    test_db.execute(
        'UPDATE deployment_flows SET stages=replace(stages, \'"scope": "item"\', \'"scope": "run"\') WHERE id=(SELECT flow FROM deployment_runs WHERE id=%s)',
        (RUN,),
    )
    test_db.commit()
    with pytest.raises(ValueError, match="shared run-level gate"):
        cmd_remove_item(RUN, ITEM, reason=REASON)
    assert _still_member(test_db)


def test_closed_member_refuses_removal(test_db):
    _red_member(test_db)
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (ITEM,))
    test_db.commit()
    with pytest.raises(ValueError, match="already closed"):
        cmd_remove_item(RUN, ITEM, reason=REASON)
    assert _still_member(test_db)


def test_failed_item_qa_resume_excludes_removed_member(test_db, monkeypatch):
    from yoke_core.domain import deploy_pipeline, deploy_pipeline_run_updates

    _red_member(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET status='failed',current_stage=%s WHERE id=%s",
        (f"{ITEM_QA_STAGE}-failed", RUN),
    )
    test_db.commit()
    _held_lock(monkeypatch)
    cmd_remove_item(RUN, ITEM, reason=REASON)
    stages = pinned_stages(test_db, RUN)
    context = {
        "run": {
            **dict(
                test_db.execute(
                    "SELECT * FROM deployment_runs WHERE id=%s", (RUN,)
                ).fetchone()
            ),
            "project": "yoke",
        },
        "members": [
            dict(row)
            for row in test_db.execute(
                "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (RUN,)
            ).fetchall()
        ],
        "stages": stages,
    }
    control = deploy_pipeline.control_plane
    monkeypatch.setattr(control, "execution_context", lambda _: context)
    monkeypatch.setattr(control, "project_field", lambda *_: "")
    monkeypatch.setattr(control, "seed_qa", lambda _: 0)
    monkeypatch.setattr(
        control, "unresolved_qa", lambda _: unresolved_blocking_qa(test_db, RUN)
    )
    monkeypatch.setattr(control, "record_qa_pass", lambda *_: None)
    monkeypatch.setattr(
        deploy_pipeline, "resolve_project_checkout_path", lambda _: "/repo"
    )
    monkeypatch.setattr(deploy_pipeline, "resolve_flow_gate_branch", lambda *_: "main")
    monkeypatch.setattr(deploy_pipeline, "_emit_run_event", lambda *_a, **_k: None)
    monkeypatch.setattr(deploy_pipeline, "_set_deploy_stage", lambda *_a, **_k: None)
    monkeypatch.setattr(deploy_pipeline, "_finalize", lambda *_a, **_k: 0)
    monkeypatch.setattr(
        deploy_pipeline.stage_checks, "check_resume_qa_gate", lambda **_: None
    )
    monkeypatch.setattr(
        deploy_pipeline_run_updates,
        "start_run",
        lambda *_: test_db.execute(
            "UPDATE deployment_runs SET status='executing' WHERE id=%s", (RUN,)
        ),
    )
    dispatched = []

    def dispatch(stage, **kwargs):
        dispatched.append((stage["name"], kwargs["member_items"]))
        return materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=RUN)

    monkeypatch.setattr(
        deploy_pipeline.stage_receipt, "dispatch_step_runner_with_receipt", dispatch
    )
    assert (
        deploy_pipeline.run_pipeline(RUN, from_stage=ITEM_QA_STAGE, sd="/tmp/sd") == 0
    )
    assert dispatched == [(ITEM_QA_STAGE, [])]
    assert not _still_member(test_db)


def test_settlement_releases_a_later_correction_without_closing_it(
    test_db, tmp_path, monkeypatch
):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    sibling = ITEM + 1
    for item in (ITEM, sibling):
        _ready_member(test_db, item, f"holder-{item}")
        _no_obligation(test_db, item, reason="no runtime obligation")
    repo, frozen, correction = release_repository(tmp_path, "settlement")
    serve_repository(monkeypatch, repo)
    for item, sha in ((ITEM, correction), (sibling, frozen)):
        record_landing_receipt(test_db, item, branch=f"member-{item}", tip=sha)
        record_dash_evidence(
            test_db,
            item_id=item,
            result_summary="landed",
            verification_summary="checked",
            verification_status="passed",
            commit_sha=sha,
            merge_sha=sha,
            touched_files=["release.txt"],
            tree_root=str(repo),
            tree_head_sha=sha,
        )
    run_id = "run-settlement-correction"
    _executing_run(test_db, run_id, (ITEM, sibling))
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s", (frozen, run_id)
    )
    test_db.commit()

    assert cmd_update(run_id, "status", "succeeded") is None

    (removal,) = membership_removals(test_db, run_id)
    assert removal["item_id"] == ITEM
    assert "not contained" in removal["reason"]
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()["status"]
        == "succeeded"
    )
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (ITEM,)).fetchone()[
            "status"
        ]
        == "release"
    )
    assert _claim_held(test_db, ITEM)
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (sibling,)).fetchone()[
            "status"
        ]
        == "done"
    )
    assert not _claim_held(test_db, sibling)
