"""Coordination-aware direct-workflow conflict survey coverage."""

from __future__ import annotations

import json

from runtime.api.domain.path_claim_task_test_support import (
    seed_item_claim,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.conflict_survey import survey_conflicts


def test_coordination_only_edge_clears_claim_and_frontier_contacts(test_db):
    candidate_id = 2201
    blocker_id = 2202
    shared_path = "src/shared_registry.py"
    insert_item(test_db, id=candidate_id, workflow_id="blitz")
    insert_item(
        test_db,
        id=blocker_id,
        workflow_id="issue",
        spec=f"## File Budget\n\n- `{shared_path}`\n",
    )
    target_id = seed_target(test_db, item_id=blocker_id, path=shared_path)
    seed_item_claim(
        test_db,
        item_id=blocker_id,
        target_ids=(target_id,),
        state="planned",
    )

    blocked = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )
    assert {row.kind for row in blocked.blockers} == {
        "frontier_scope",
        "path_claim",
    }

    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, created_at) VALUES (%s, %s, 'coordination_only', "
        "'fact:merged', 'test', %s, '2026-07-29T00:00:00Z')",
        (
            f"YOK-{candidate_id}",
            f"YOK-{blocker_id}",
            "decision=coordination_only. shared_paths=src/shared_registry.py. "
            "independence_evidence=disjoint functions",
        ),
    )
    test_db.commit()

    coordinated = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )
    assert coordinated.clear is True
    assert coordinated.blockers == ()

    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, created_at) VALUES (%s, %s, 'activation', "
        "'fact:merged', 'test', 'ordered change', '2026-07-29T00:01:00Z')",
        (f"YOK-{candidate_id}", f"YOK-{blocker_id}"),
    )
    test_db.commit()

    ordered = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )
    assert ordered.clear is False
    assert {row.kind for row in ordered.blockers} == {
        "frontier_scope",
        "path_claim",
    }


def test_optional_dash_ignores_frozen_planned_scope_and_claim(test_db):
    candidate_id = 2210
    blocker_id = 2211
    shared_path = "src/frozen_scope.py"
    insert_item(test_db, id=candidate_id, workflow_id="dash")
    insert_item(
        test_db,
        id=blocker_id,
        workflow_id="issue",
        frozen=1,
        spec=f"## File Budget\n\n- `{shared_path}`\n",
    )
    target_id = seed_target(test_db, item_id=blocker_id, path=shared_path)
    seed_item_claim(
        test_db,
        item_id=blocker_id,
        target_ids=(target_id,),
        state="planned",
    )

    survey = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )

    assert survey.clear is True
    assert survey.blockers == ()


def test_optional_dash_proposes_narrowing_for_downstream_frozen_claim(test_db):
    candidate_id = 2216
    blocker_id = 2217
    shared_path = "src/downstream_frozen_scope.py"
    insert_item(test_db, id=candidate_id, workflow_id="dash")
    insert_item(
        test_db,
        id=blocker_id,
        workflow_id="issue",
        frozen=1,
        spec=f"## File Budget\n\n- `{shared_path}`\n",
    )
    target_id = seed_target(test_db, item_id=blocker_id, path=shared_path)
    claim_id = seed_item_claim(
        test_db,
        item_id=blocker_id,
        target_ids=(target_id,),
        state="planned",
    )
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, created_at) VALUES (%s, %s, 'activation', "
        "'fact:merged', 'test', 'upstream dash lands first', "
        "'2026-08-18T00:00:00Z')",
        (f"YOK-{blocker_id}", f"YOK-{candidate_id}"),
    )
    test_db.commit()

    survey = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )

    assert [row.kind for row in survey.blockers] == ["path_claim"]
    detail = survey.blockers[0].detail
    assert f"--claim-id {claim_id}" in detail
    assert f"--remove-paths {shared_path}" in detail
    assert f"--item YOK-{blocker_id}" in detail
    assert "--integration-target main" in detail


def test_selected_dash_path_claims_keep_frozen_planned_scope_blocking(test_db):
    candidate_id = 2212
    blocker_id = 2213
    shared_path = "src/frozen_required_scope.py"
    insert_item(
        test_db,
        id=candidate_id,
        workflow_id="dash",
        workflow_posture=json.dumps({"path_claims": True}),
    )
    insert_item(
        test_db,
        id=blocker_id,
        workflow_id="issue",
        frozen=1,
        spec=f"## File Budget\n\n- `{shared_path}`\n",
    )
    target_id = seed_target(test_db, item_id=blocker_id, path=shared_path)
    seed_item_claim(
        test_db,
        item_id=blocker_id,
        target_ids=(target_id,),
        state="planned",
    )

    survey = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )

    assert {row.kind for row in survey.blockers} == {
        "frontier_scope",
        "path_claim",
    }


def test_optional_dash_keeps_active_frozen_claim_blocking(test_db):
    candidate_id = 2214
    blocker_id = 2215
    shared_path = "src/frozen_active_scope.py"
    insert_item(test_db, id=candidate_id, workflow_id="dash")
    insert_item(test_db, id=blocker_id, workflow_id="issue", frozen=1)
    target_id = seed_target(test_db, item_id=blocker_id, path=shared_path)
    seed_item_claim(
        test_db,
        item_id=blocker_id,
        target_ids=(target_id,),
        state="active",
    )

    survey = survey_conflicts(
        test_db,
        item_id=candidate_id,
        touch_paths=[shared_path],
    )

    assert {row.kind for row in survey.blockers} == {"path_claim"}
