"""Stage proof and final delivery have independent membership and done gates."""

import pytest

from runtime.api.domain.test_dash_post_deploy_done_consumption import (
    _accept_member_qa,
    _bind_original,
    _transition_done,
)
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_post_deploy_original_pass_needs_admission import (
    _record_evidence,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from yoke_core.domain.deployment_item_completion_runs import completion_runs
from yoke_core.domain.gate_satisfier_resolution import record_delivery_evidence_rung
from yoke_core.domain.deployment_member_post_deploy_admission import (
    post_deploy_admission_split,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_member_targeting import (
    holder_covers_run,
    run_needs_member,
)


def _pair(conn, *, item_id):
    _insert_dash(conn, item_id=item_id, status="release")
    sources = {}
    for environment in ("stage", "prod"):
        source = _bind_original(conn, item_id=item_id)
        conn.execute(
            "UPDATE qa_requirements SET target_env=%s WHERE id=%s",
            (environment, source),
        )
        conn.commit()
        _seed_selected_requirement_run(
            conn,
            run_id=f"run-{environment}",
            item_id=item_id,
            requirement_id=source,
            environment=environment,
        )
        conn.execute(
            "UPDATE deployment_flows SET target_tier='persistent',target_environment_id="
            "(SELECT id FROM environments WHERE project_id=1 AND name=%s) WHERE id=%s",
            (environment, f"flow-run-{environment}"),
        )
        conn.execute(
            "UPDATE deployment_runs SET target_tier='persistent',target_environment_id="
            "(SELECT id FROM environments WHERE project_id=1 AND name=%s) WHERE id=%s",
            (environment, f"run-{environment}"),
        )
        sources[environment] = source
    conn.commit()
    return sources


def test_targeted_memberships_admit_only_their_own_obligations(test_db):
    item_id = 9680
    sources = _pair(test_db, item_id=item_id)
    for environment, source in sources.items():
        admitted, _ = post_deploy_admission_split(
            test_db, run_id=f"run-{environment}", item_id=item_id
        )
        assert admitted == (source,)
        assert run_needs_member(test_db, run_id=f"run-{environment}", item_id=item_id)
    assert not holder_covers_run(
        test_db, holder_id="run-stage", run_id="run-prod", item_id=item_id
    )
    assert not holder_covers_run(
        test_db, holder_id="run-prod", run_id="run-stage", item_id=item_id
    )
    assert [run["id"] for run in completion_runs(test_db, item_id)] == ["run-prod"]


def test_no_stage_obligation_keeps_member_off_supplemental_run(test_db):
    item_id = 9681
    sources = _pair(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s WHERE id=%s",
        ("2026-10-06T00:00:00Z", sources["stage"]),
    )
    test_db.commit()
    assert not run_needs_member(test_db, run_id="run-stage", item_id=item_id)
    assert run_needs_member(test_db, run_id="run-prod", item_id=item_id)


@pytest.mark.parametrize("first", ["stage", "prod"])
def test_done_requires_both_targets_to_pass(test_db, monkeypatch, first):
    item_id = 9682
    sources = _pair(test_db, item_id=item_id)
    _record_evidence(test_db, item_id=item_id)
    _accept_member_qa(test_db, run_id=f"run-{first}", item_id=item_id)
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources[first]
    )
    assert not _transition_done(
        test_db, item_id=item_id, monkeypatch=monkeypatch
    ).primary_success
    second = "prod" if first == "stage" else "stage"
    _accept_member_qa(test_db, run_id=f"run-{second}", item_id=item_id)
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources[second]
    )
    record_delivery_evidence_rung(test_db, item_id=item_id, merge_recorded=True)
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success, outcome.error
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "done"
    )
    # Both targets' admitted evidence was written to this one control-plane connection.
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_member_item_id=%s",
            (item_id,),
        ).fetchone()[0]
        >= 2
    )


def test_stage_failure_blocks_after_production_passes(test_db, monkeypatch):
    item_id = 9683
    sources = _pair(test_db, item_id=item_id)
    _record_evidence(test_db, item_id=item_id)
    _accept_member_qa(test_db, run_id="run-prod", item_id=item_id)
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-stage",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    insert_qa_run(
        test_db, qa_requirement_id=result["created_requirement_ids"][0], verdict="fail"
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id=%s", ("run-stage",)
    )
    test_db.commit()
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["stage"]
    )
    assert not _transition_done(
        test_db, item_id=item_id, monkeypatch=monkeypatch
    ).primary_success


def test_prod_authors_and_materializes_stage_plan_without_dispatching_it(
    test_db, monkeypatch
):
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )
    from yoke_core.domain.qa_execution_environment_target import (
        resolve_plan_execution_target,
        QaExecutionTargetError,
    )

    item_id = 9684
    _pair(test_db, item_id=item_id)
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    test_db.execute(
        "UPDATE environments SET settings=%s WHERE project_id=1 AND name='prod'",
        ('{"qa":{"restrict_execution_to_self":true}}',),
    )
    test_db.commit()
    plan = create_plan(
        test_db, project="yoke", slug="stage-release-proof", target_environment="stage"
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "stage-proof",
                "position": 1,
                "method_id": "command",
                "instructions": "Check deployed stage behavior",
                "expected_outcome": "Stage proof passes",
                "method_config": {"command": "true"},
            }
        ],
    )
    attach_plan_to_item(
        test_db,
        plan_id=int(plan["id"]),
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    materialize_for_item(test_db, item_id=item_id, transition_id="release")
    rows = test_db.execute(
        "SELECT id,execution_target_json FROM qa_requirements WHERE item_id=%s AND plan_id=%s",
        (item_id, int(plan["id"])),
    ).fetchall()
    import json

    assert rows and all(
        json.loads(str(row[1]))["environment"]["name"] == "stage" for row in rows
    )
    admitted, _ = post_deploy_admission_split(
        test_db, run_id="run-stage", item_id=item_id
    )
    assert all(int(row[0]) in admitted for row in rows)
    # Actual standalone dispatch retains its runtime restriction; deployment
    # QA later supplies the receipt-bound execution target that exempts it.
    with pytest.raises(QaExecutionTargetError, match="cannot execute QA target"):
        resolve_plan_execution_target(test_db, plan_id=int(plan["id"]))


def test_composition_enrolls_both_runs_and_omits_unneeded_stage_members(test_db):
    from types import SimpleNamespace
    from yoke_core.domain.deployment_run_carried_membership import (
        enroll_carried_members,
    )
    from yoke_core.domain.deployment_run_unheld_candidates import CandidateCustody

    item_id = 9685
    _pair(test_db, item_id=item_id)
    other_id = item_id + 1
    _insert_dash(test_db, item_id=other_id, status="release")
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", ("flow-run-prod", other_id)
    )
    test_db.execute("DELETE FROM deployment_run_items WHERE item_id=%s", (item_id,))
    test_db.execute(
        "UPDATE deployment_runs SET status='created',composition_frozen_at=NULL WHERE id IN (%s,%s)",
        ("run-stage", "run-prod"),
    )
    test_db.commit()
    carried = {
        "derivation": {"contents_known": True},
        "items": [{"item_id": item_id}, {"item_id": other_id}],
    }
    custody = SimpleNamespace(
        require=lambda: CandidateCustody(enrollable=(item_id, other_id), held=())
    )
    stage_members = enroll_carried_members(
        test_db, "run-stage", carried_work=carried, custody=custody
    )
    prod_members = enroll_carried_members(
        test_db, "run-prod", carried_work=carried, custody=custody
    )
    assert len(stage_members) == 1
    assert len(prod_members) == 2
    rows = test_db.execute(
        "SELECT run_id,item_id FROM deployment_run_items ORDER BY run_id,item_id"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("run-prod", item_id),
        ("run-prod", other_id),
        ("run-stage", item_id),
    ]


def test_unadmitted_notice_only_names_targets_no_composed_sibling_admits(test_db):
    from yoke_core.domain.deployment_member_post_deploy_admission import (
        unadmitted_post_deploy_notice,
    )

    item_id = 9687
    _pair(test_db, item_id=item_id)
    assert unadmitted_post_deploy_notice(test_db, "run-prod") == ""
    assert unadmitted_post_deploy_notice(test_db, "run-stage") == ""
    source = _bind_original(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET target_env=%s WHERE id=%s", ("uncovered", source)
    )
    test_db.commit()
    notice = unadmitted_post_deploy_notice(test_db, "run-prod")
    assert f"#{source}" in notice and "target_env=uncovered" in notice


def test_stage_proof_for_another_candidate_cannot_close_current_delivery(test_db):
    item_id = 9688
    sources = _pair(test_db, item_id=item_id)
    _accept_member_qa(test_db, run_id="run-stage", item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s",
        ("d" * 40, "run-prod"),
    )
    test_db.commit()
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["stage"]
    )


def test_supplemental_run_finishes_without_final_item_close_out(test_db, monkeypatch):
    from runtime.api.domain.test_deployment_run_auto_completion import _held_lock
    from yoke_core.domain.deployment_run_auto_completion import _readiness

    item_id = 9689
    _pair(test_db, item_id=item_id)
    _accept_member_qa(test_db, run_id="run-stage", item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='member-qa' WHERE id=%s",
        ("run-stage",),
    )
    test_db.commit()
    _held_lock(monkeypatch)
    ready, reason = _readiness(test_db, "run-stage")
    assert ready is not None, reason
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "release"
    )
