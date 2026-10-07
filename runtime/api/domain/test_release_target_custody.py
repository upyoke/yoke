"""Supplemental target routing preserves established landing custody."""

import json
from unittest.mock import patch

import pytest

from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.domain.test_dash_post_deploy_done_consumption import _bind_original
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_run_held_member_composition import (
    _carried_landing,
    _holder,
    _members,
    CARRIER_FLOW,
    LANDED_ITEM_ID,
)
from yoke_core.domain.deployment_run_member_targeting import (
    holder_covers_run,
    member_selected_requirement_ids,
    needed_member_ids,
    covering_holder_pairs,
    companion_requirement_sets,
)
from yoke_core.domain.deployment_run_unheld_candidates import candidate_custody
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.schema_read_scope import composition_reads


def test_recorded_legacy_holder_keeps_custody_without_qa_selection(
    test_db, tmp_path, monkeypatch
):
    _carried_landing(test_db, tmp_path, monkeypatch, item_flow=CARRIER_FLOW)
    _holder(test_db, "run-legacy-holder", status="succeeded", flow=CARRIER_FLOW)
    test_db.execute(
        "UPDATE deployment_flows SET definition_schema_version=1,stages='[]' WHERE id=%s",
        (CARRIER_FLOW,),
    )
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=NULL,requirement_selection=NULL WHERE run_id=%s",
        ("run-legacy-holder",),
    )
    source = _bind_original(test_db, item_id=LANDED_ITEM_ID)
    test_db.commit()
    assert source
    assert candidate_custody(test_db, "run-candidate").held_ids == frozenset(
        {LANDED_ITEM_ID}
    )
    ok, detail = cmd_validate_composition("run-candidate")
    assert ok, detail
    assert _members(test_db) == []


def test_final_target_holder_retains_custody_for_later_targeted_intake(test_db):
    item_id = 9690
    _pair(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_runs SET target_environment_id=(SELECT id FROM environments WHERE project_id=1 AND name='prod') WHERE id='run-stage'"
    )
    fresh = _bind_original(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET target_env='prod' WHERE id=%s", (fresh,)
    )
    test_db.commit()
    assert holder_covers_run(
        test_db, holder_id="run-prod", run_id="run-stage", item_id=item_id
    )


def test_pending_selection_reads_waived_requirements_without_locks(test_db):
    item_id = 9691
    sources = _pair(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=NULL,requirement_selection=%s WHERE run_id='run-stage'",
        (
            json.dumps(
                {"schema": 1, "requirement_ids": [sources["stage"]], "plan_ids": []}
            ),
        ),
    )
    test_db.execute(
        "UPDATE qa_requirements SET waived_at='2026-10-06T00:00:00Z' WHERE id=%s",
        (sources["stage"],),
    )
    test_db.commit()
    with patch.object(test_db, "execute", wraps=test_db.execute) as reads:
        selected = member_selected_requirement_ids(
            test_db, run_id="run-stage", item_id=item_id
        )
    assert selected == frozenset({sources["stage"]})
    assert not any(
        "FOR UPDATE" in str(call.args[0]).upper() for call in reads.call_args_list
    )


@pytest.mark.parametrize("reader", ["needed", "holders", "companions"])
def test_target_composition_read_count_is_independent_of_member_count(test_db, reader):
    first = 9700
    _pair(test_db, item_id=first)
    ids = tuple(range(first, first + 20))
    for item_id in ids[1:]:
        _insert_dash(test_db, item_id=item_id, status="release")
        test_db.execute(
            "UPDATE items SET deployment_flow='flow-run-prod' WHERE id=%s", (item_id,)
        )
        test_db.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at,requirement_selection) VALUES ('run-prod',%s,'2026-10-06T00:00:00Z',%s)",
            (item_id, json.dumps({"schema": 1, "requirement_ids": [], "plan_ids": []})),
        )
    test_db.commit()

    def read(subjects):
        if reader == "needed":
            return needed_member_ids(test_db, run_id="run-stage", item_ids=subjects)
        if reader == "holders":
            return covering_holder_pairs(
                test_db,
                run_id="run-stage",
                item_ids=subjects,
                holders=[{"run_id": "run-prod"}],
            )
        return companion_requirement_sets(
            test_db, run_id="run-stage", item_ids=subjects
        )

    with patch.object(test_db, "execute", wraps=test_db.execute) as reads:
        with composition_reads():
            read(ids[:1])
        single = reads.call_count
        reads.reset_mock()
        with composition_reads():
            read(ids)
        assert reads.call_count == single
        assert not any(
            "FOR UPDATE" in str(call.args[0]).upper() for call in reads.call_args_list
        )


@pytest.mark.parametrize("frozen", [False, True])
def test_plan_selections_read_identity_without_snapshotting_cases(test_db, frozen):
    from yoke_core.domain.qa_plan_management import create_plan

    item_id = 9692
    sources = _pair(test_db, item_id=item_id)
    plan = create_plan(
        test_db, project="yoke", slug="selected-stage-cases", target_environment="stage"
    )
    plan_id = int(plan["id"])
    test_db.execute(
        "UPDATE qa_requirements SET plan_id=%s,plan_case_key='recorded-case',waived_at='2026-10-06T00:00:00Z' WHERE id=%s",
        (plan_id, sources["stage"]),
    )
    later = _bind_original(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET plan_id=%s,plan_case_key='later-case' WHERE id=%s",
        (plan_id, later),
    )
    snapshot = (
        json.dumps(
            {
                "requirements": [],
                "plans": [
                    {"plan": {"id": plan_id}, "cases": [{"case_key": "recorded-case"}]}
                ],
            }
        )
        if frozen
        else None
    )
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s,requirement_selection=%s WHERE run_id='run-stage'",
        (
            snapshot,
            json.dumps({"schema": 1, "requirement_ids": [], "plan_ids": [plan_id]}),
        ),
    )
    test_db.commit()
    with patch.object(test_db, "execute", wraps=test_db.execute) as reads:
        selected = member_selected_requirement_ids(
            test_db, run_id="run-stage", item_id=item_id
        )
    expected = {sources["stage"]} if frozen else {sources["stage"], later}
    assert selected == frozenset(expected)
    assert not any(
        "FOR UPDATE" in str(call.args[0]).upper() for call in reads.call_args_list
    )


def _pin(conn, run_id, *, project_id, sha):
    """Record *sha* as the commit *run_id* ships for *project_id*."""
    if project_id == 1:
        conn.execute(
            "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s", (sha, run_id)
        )
    else:
        conn.execute(
            "UPDATE deployment_runs SET bound_sources=%s WHERE id=%s",
            (
                json.dumps(
                    {
                        "schema": 1,
                        "projects": [{"project_id": project_id, "commit_sha": sha}],
                    }
                ),
                run_id,
            ),
        )


@pytest.mark.parametrize("project_id", [1, 2])
@pytest.mark.parametrize("same_commit", [True, False])
def test_production_holder_keeps_stage_owing_item_only_off_another_commit(
    test_db, project_id, same_commit
):
    """Production custody yields to the stage run on its own commit only.

    Close-out credits stage proof against the commit production ships, so the
    stage half of a release pair enrolls a stage-owing member the production
    half already holds, while a stage run on any other commit leaves it alone.
    """
    item_id = 9693 + project_id + (10 if same_commit else 0)
    _pair(test_db, item_id=item_id)
    test_db.execute("UPDATE items SET project_id=%s WHERE id=%s", (project_id, item_id))
    _pin(test_db, "run-prod", project_id=project_id, sha="a" * 40)
    _pin(
        test_db,
        "run-stage",
        project_id=project_id,
        sha="a" * 40 if same_commit else "b" * 40,
    )
    test_db.commit()
    assert needed_member_ids(
        test_db, run_id="run-stage", item_ids=(item_id,)
    ) == frozenset({item_id})
    assert (
        holder_covers_run(
            test_db, holder_id="run-prod", run_id="run-stage", item_id=item_id
        )
        is not same_commit
    )


def test_skip_notice_names_the_commit_a_production_holder_pinned(test_db):
    from yoke_core.domain.deployment_run_skipped_candidates import _describe_held
    from yoke_core.domain.deployment_run_unheld_candidates import HeldCandidate

    item_id = 9720
    _pair(test_db, item_id=item_id)
    _pin(test_db, "run-prod", project_id=1, sha="a" * 40)
    test_db.commit()
    record = HeldCandidate(
        item_id=item_id, item_ref="YOK-1", run_id="run-prod", run_status="executing"
    )
    line = _describe_held(test_db, "run-stage", record)
    assert line.startswith("YOK-1 held by run-prod (executing) on commit " + "a" * 40)
    assert "stage proof credits only against that commit" in line
    assert _describe_held(test_db, "run-prod", record) == (
        "YOK-1 held by run-prod (executing)"
    )
