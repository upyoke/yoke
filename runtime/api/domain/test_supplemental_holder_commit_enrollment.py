"""Pending supplemental proof enrolls again when the candidate changes."""

import json

import pytest

from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.fixtures.carried_release_candidate import (
    git,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_member_targeting import holder_covers_run
from yoke_core.domain.deployment_run_unheld_candidates import resolve_candidate_custody


@pytest.mark.parametrize("selection", ["snapshot", "explicit", "unselected"])
@pytest.mark.parametrize("holder_status", ["executing", "succeeded"])
@pytest.mark.parametrize("same_commit", [False, True])
def test_stage_holder_only_prevents_enrollment_on_same_commit(
    test_db, tmp_path, monkeypatch, selection, holder_status, same_commit
):
    item_id = 9690
    sources = _pair(test_db, item_id=item_id)
    ref = item_ref(test_db, item_id)
    repo, _, landing = release_repository(tmp_path, ref)
    (repo / "release.txt").write_text("new candidate\n", encoding="utf-8")
    git(repo, "commit", "-am", "Prepare new candidate")
    candidate = git(repo, "rev-parse", "HEAD")
    serve_repository(monkeypatch, repo)
    record_landing_receipt(test_db, item_id, branch="main", tip=landing)
    test_db.execute(
        "UPDATE items SET merged_at='2026-09-14T00:10:00Z' WHERE id=%s",
        (item_id,),
    )
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s,status=%s WHERE id='run-stage'",
        (candidate if same_commit else landing, holder_status),
    )
    # Production carries the new candidate but cannot answer its Stage proof.
    test_db.execute(
        "UPDATE deployment_runs SET release_lineage=%s WHERE id='run-prod'",
        (candidate,),
    )
    if selection != "snapshot":
        selected = (
            json.dumps({"requirement_ids": [sources["stage"]], "plan_ids": []})
            if selection == "explicit"
            else None
        )
        test_db.execute(
            "UPDATE deployment_run_items SET requirement_snapshot=NULL,"
            "requirement_selection=%s WHERE run_id='run-stage'",
            (selected,),
        )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at,target_tier,target_environment_id) "
        "SELECT 'run-new-stage',project_id,flow,%s,'created',created_at,"
        "target_tier,target_environment_id FROM deployment_runs WHERE id='run-stage'",
        (candidate,),
    )
    test_db.commit()

    assert (
        holder_covers_run(
            test_db, holder_id="run-stage", run_id="run-new-stage", item_id=item_id
        )
        is same_commit
    )
    custody = resolve_candidate_custody(test_db, "run-new-stage")
    resolved = custody.require()
    assert resolved.held_ids == (frozenset({item_id}) if same_commit else frozenset())
    assert resolved.enrollable == (() if same_commit else (item_id,))
    enrolled = enroll_carried_members(
        test_db,
        "run-new-stage",
        carried_work={"derivation": {"contents_known": True}, "items": []},
        custody=custody,
    )
    assert enrolled == (() if same_commit else (ref,))
    assert test_db.execute(
        "SELECT COUNT(*) FROM deployment_run_items WHERE run_id='run-new-stage'"
    ).fetchone()[0] == (0 if same_commit else 1)
