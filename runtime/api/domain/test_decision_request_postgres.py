"""Postgres authority proof for the additive decision-request substrate."""

from __future__ import annotations

import json

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.decision_request_authority import (
    pending_requests_for_actor,
)
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_related_evidence import related_screenshot_evidence
from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables


def test_postgres_schema_authority_and_transactional_resolution(test_db):
    create_decision_request_tables(test_db)
    org_id = 9001
    project_id = 9010
    test_db.execute(
        "INSERT INTO organizations (id, slug, name, created_at) "
        "VALUES (%s, 'inbox-proof', 'Inbox proof', '2026-07-26T00:00:00Z')",
        (org_id,),
    )
    test_db.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at, org_id) "
        "VALUES (%s, 'inbox-proof', 'Inbox proof', 'IBX', "
        "'2026-07-26T00:00:00Z', %s)",
        (project_id, org_id),
    )
    actor_ids = [9101, 9102]
    for actor_id, label in zip(actor_ids, ("originator", "owner")):
        test_db.execute(
            "INSERT INTO actors (id, kind, created_at) "
            "VALUES (%s, 'human', '2026-07-26T00:00:00Z')",
            (actor_id,),
        )
        test_db.execute(
            "UPDATE actors SET name = %s WHERE id = %s",
            (label, actor_id),
        )
    role_id = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9201, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, %s, %s, '2026-07-26T00:00:00Z')",
        (actor_ids[1], project_id, role_id),
    )
    test_db.commit()

    request, created = create_decision_request(
        test_db,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key="17:done",
        project_id=project_id,
        originator_actor_id=actor_ids[0],
        role_authorities=[RoleAuthority("project", project_id, "owner")],
        subject_context={
            "item_id": 17,
            "item_ref": "IBX-17",
            "item_title": "Transactional resolution proof",
            "from_stage": "reviewing-implementation",
            "to_stage": "done",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "branch_changes": {
                "branch": "IBX-17",
                "commit_sha": None,
                "touched_files": [],
                "summary": "No changed files are recorded.",
            },
            "approval_source": {
                "kind": "workflow_approval_default",
                "entry": "approval_defaults.done",
            },
        },
    )
    assert created is True
    assert pending_requests_for_actor(test_db, actor_ids[1])[0]["id"] == (request["id"])
    resolved = resolve_decision_request(
        test_db,
        request["id"],
        actor_id=actor_ids[1],
        action="approve",
    )
    assert resolved["status"] == "resolved"
    assert [
        row[0]
        for row in test_db.execute(
            "SELECT event_name FROM events "
            "WHERE event_name LIKE 'DecisionRequest%' ORDER BY created_at, id"
        ).fetchall()
    ] == ["DecisionRequestCreated", "DecisionRequestResolved"]


def test_pending_request_shows_screenshots_attached_after_it_was_created(test_db):
    create_decision_request_tables(test_db)
    project_id = 9020
    test_db.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        "VALUES (%s, 'live-evidence-proof', 'Live evidence proof', 'LEP', "
        "'2026-07-26T00:00:00Z')",
        (project_id,),
    )
    actor_id = 9110
    test_db.execute(
        "INSERT INTO actors (id, kind, created_at) "
        "VALUES (%s, 'human', '2026-07-26T00:00:00Z')",
        (actor_id,),
    )
    role_id = test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9202, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, %s, %s, '2026-07-26T00:00:00Z')",
        (actor_id, project_id, role_id),
    )
    test_db.commit()

    # The qa tables exist but hold nothing yet, so the frozen snapshot this
    # request is created with -- exactly as the lifecycle-gate builder would
    # compute it -- records no attached screenshot.
    create_qa_catalog_tables(test_db)
    frozen_evidence = related_screenshot_evidence(
        test_db, item_id=27, expected_revision="a" * 40
    )
    assert frozen_evidence["state"] == "absent"

    request, _ = create_decision_request(
        test_db,
        kind="lifecycle_transition_approval",
        subject_type="item_transition",
        subject_key="27:done",
        project_id=project_id,
        role_authorities=[RoleAuthority("project", project_id, "owner")],
        subject_context={
            "item_id": 27,
            "item_ref": "LEP-27",
            "item_title": "Live evidence proof",
            "from_stage": "reviewing-implementation",
            "to_stage": "done",
            "workflow_id": "issue",
            "workflow_version_id": 1,
            "branch_changes": {
                "branch": "LEP-27",
                "commit_sha": "a" * 40,
                "touched_files": [],
                "summary": "No changed files are recorded.",
            },
            "approval_source": {
                "kind": "workflow_approval_default",
                "entry": "approval_defaults.done",
            },
            "evidence": frozen_evidence,
        },
    )
    assert request["subject_context"]["evidence"]["state"] == "absent"

    requirement_id = test_db.execute(
        "INSERT INTO qa_requirements "
        "(item_id, plan_case_key, method_id, method_name, expected_outcome, "
        "runner_id, verdict_path, qa_kind, qa_phase, blocking_mode, created_at) "
        "VALUES (27, 'done-proof', 'browser-inspection', 'Browser inspection', "
        "'The saved state is visible.', 'browser_substrate', 'agent', "
        "'plan_case', 'verification', 'blocking', '2026-07-26T00:00:00Z') "
        "RETURNING id"
    ).fetchone()[0]
    run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, raw_result, "
        "created_at) VALUES (%s, 'agent', 'manual_acceptance', 'pass', %s, "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (requirement_id, '{"verification_tree": {"head_sha": "' + "a" * 40 + '"}}'),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle, created_at) "
        "VALUES (%s, 'screenshot', %s, '2026-07-26T00:00:00Z')",
        (run_id, '{"backend":"local","path":"/tmp/live-evidence.png"}'),
    )
    test_db.commit()

    pending = pending_requests_for_actor(test_db, actor_id)[0]
    assert pending["id"] == request["id"]
    # The returned copy recomputes evidence against the same subject and
    # revision, so a still-pending read sees the screenshot attached since.
    evidence = pending["subject_context"]["evidence"]
    assert evidence["state"] == "attached"
    assert evidence["screenshot_count"] == 1
    # The stored row is never rewritten to match.
    stored = json.loads(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s",
            (request["id"],),
        ).fetchone()[0]
    )
    assert stored["evidence"]["state"] == "absent"
    assert stored["evidence"]["screenshot_count"] == 0

    resolved = resolve_decision_request(
        test_db, request["id"], actor_id=actor_id, action="approve"
    )
    # Once resolved, the request is no longer open to answer, so its history
    # carries the original frozen snapshot rather than the live recompute.
    assert resolved["subject_context"]["evidence"]["state"] == "absent"
