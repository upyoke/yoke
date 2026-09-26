"""What a halted run reports, and to whom it offers the answer."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_run_gates import run_gates
from yoke_core.domain.deployment_run_list_read import list_deployment_runs
from yoke_core.domain.qa_catalog_schema import create_qa_catalog_tables
from yoke_core.domain.qa_review_requests import ensure_qa_review_request

RUN_ID = "run-gate-proof"


def _seed_run_awaiting_approval(conn) -> tuple[int, int]:
    """A run suspended on a prod approval its project owner may answer."""
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Gate test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Gate test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    environment_id = int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
        ).fetchone()[0]
    )
    originator = int(
        conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    owner = int(
        conn.execute("SELECT id FROM actors ORDER BY id DESC LIMIT 1").fetchone()[0]
    )
    role = int(
        conn.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (9401, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
            "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
            "RETURNING id"
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') ON CONFLICT DO NOTHING",
        (owner, role),
    )
    conn.execute(
        "INSERT INTO deployment_flows (id, project_id, name, stages, created_at) "
        "VALUES ('gate-proof', 1, 'Gate proof', "
        '\'[{"name":"approve-prod","step_runner":"human-approval",'
        '"approvals":{"roles":["owner"],"actors":[]}}]\', '
        "'2026-07-26T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "release_lineage, status, current_stage, created_at) "
        "VALUES (%s, 1, 'gate-proof', 'persistent', %s, 'lineage-gate-proof', "
        "'executing', 'approve-prod', '2026-07-26T00:00:00Z')",
        (RUN_ID, environment_id),
    )
    conn.commit()
    evaluate_deployment_stage_approval(
        conn,
        run_id=RUN_ID,
        stage="approve-prod",
        originator_actor_id=originator,
    )
    conn.commit()
    return owner, originator


def test_a_halted_run_reports_its_gate_with_the_decision_it_carries(test_db):
    create_decision_request_tables(test_db)
    owner, _originator = _seed_run_awaiting_approval(test_db)

    gates = run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID]

    assert len(gates) == 1
    gate = gates[0]
    assert gate["kind"] == "deployment_stage_approval"
    # The card reads the same subject_context the Inbox row does, so the two
    # surfaces cannot describe one decision differently.
    assert gate["subject_context"]["stage"] == "approve-prod"
    assert gate["subject_context"]["shipping"]["target_environment"] == "prod"
    assert gate["can_act"] is True
    assert gate["authority_reason"] == "project owner"
    assert gate["decided_by_you"] is False


def test_a_reader_without_standing_still_sees_the_run_is_halted(test_db):
    # Hiding a gate the reader cannot answer would leave the card claiming a
    # pipeline is moving when it has stopped. What varies is the offer, not
    # the fact.
    create_decision_request_tables(test_db)
    owner, originator = _seed_run_awaiting_approval(test_db)
    assert originator != owner

    gates = run_gates(test_db, [RUN_ID], actor_id=originator)[RUN_ID]

    assert len(gates) == 1
    assert gates[0]["can_act"] is False
    assert gates[0]["authority_reason"] is None


def test_a_run_with_nothing_pending_reports_no_gate(test_db):
    create_decision_request_tables(test_db)
    _seed_run_awaiting_approval(test_db)

    assert run_gates(test_db, ["run-not-halted"], actor_id=None) == {}
    assert run_gates(test_db, [], actor_id=None) == {}


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_resolved_stage_approval_keeps_its_human_record_without_actions(test_db, action):
    create_decision_request_tables(test_db)
    owner, _originator = _seed_run_awaiting_approval(test_db)
    request_id = run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID][0]["request_id"]
    decided_at = "2026-07-26T01:02:03Z"
    test_db.execute(
        "UPDATE decision_requests SET status='resolved', resolution_action=%s, "
        "resolution_actor_id=%s, resolved_at=%s WHERE id=%s",
        (action, owner, decided_at, request_id),
    )
    test_db.commit()

    gate = run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID][0]
    assert gate["status"] == "resolved"
    assert gate["resolution_action"] == action
    assert gate["resolved_at"] == decided_at
    assert gate["resolved_by"] == test_db.execute(
        "SELECT name FROM actors WHERE id=%s", (owner,)
    ).fetchone()[0]
    assert gate["actions"] == []
    assert gate["can_act"] is False


@pytest.mark.parametrize("member_scoped", [False, True])
@pytest.mark.parametrize("action", ["approve", "reject"])
def test_qa_review_stays_on_run_card_after_human_decision(
    test_db, member_scoped, action,
):
    create_decision_request_tables(test_db)
    owner, originator = _seed_run_awaiting_approval(test_db)
    create_qa_catalog_tables(test_db)
    member_id = None
    if member_scoped:
        workflow_version = int(test_db.execute(
            "SELECT current_version_id FROM workflows WHERE id='issue'"
        ).fetchone()[0])
        next_sequence = int(test_db.execute(
            "SELECT COALESCE(MAX(project_sequence), 0) + 1 FROM items "
            "WHERE project_id=1"
        ).fetchone()[0])
        member_id = int(test_db.execute(
            "INSERT INTO items "
            "(title, status, priority, created_at, updated_at, source, owner, "
            "project_id, project_sequence, workflow_id, workflow_version_id) "
            "VALUES ('Member QA review', 'implementing', 'medium', "
            "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z', %s, %s, "
            "1, %s, 'issue', %s) RETURNING id",
            (str(originator), str(owner), next_sequence, workflow_version),
        ).fetchone()[0])
        test_db.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, '2026-07-26T00:00:00Z')",
            (RUN_ID, member_id),
        )
    requirement_id = int(test_db.execute(
        "INSERT INTO qa_requirements "
        "(deployment_run_id, deployment_stage, deployment_member_item_id, "
        "expected_outcome, "
        "qa_kind, qa_phase, blocking_mode, verdict_path, created_at) "
        "VALUES (%s, %s, %s, 'The deployed release is verified.', "
        "'deployment_stage_acceptance', 'post_deploy', 'blocking', 'agent', "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (RUN_ID, "item-qa" if member_scoped else "run-visual-qa", member_id),
    ).fetchone()[0])
    qa_run_id = int(test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "created_at) VALUES (%s, 'agent', 'deployment_stage_acceptance', "
        "'undetermined', 'Human acceptance required', '2026-07-26T00:00:00Z') "
        "RETURNING id",
        (requirement_id,),
    ).fetchone()[0])
    test_db.commit()
    request, created = ensure_qa_review_request(
        test_db, requirement_id=requirement_id, run_id=qa_run_id,
        originator_actor_id=originator,
    )
    assert created is True
    assert request["kind"] == "qa_needs_review"
    assert request["subject_context"]["subject"]["deployment_member_item_id"] == member_id

    pending = next(gate for gate in run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID]
                   if gate["request_id"] == request["id"])
    assert pending["status"] == "pending"
    assert pending["can_act"] is True
    assert "approve" in pending["actions"]

    decided_at = "2026-07-26T01:02:03Z"
    test_db.execute(
        "UPDATE decision_requests SET status='resolved', resolution_action=%s, "
        "resolution_actor_id=%s, resolved_at=%s WHERE id=%s",
        (action, owner, decided_at, request["id"]),
    )
    test_db.commit()
    resolved = next(gate for gate in run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID]
                    if gate["request_id"] == request["id"])
    assert resolved["status"] == "resolved"
    assert resolved["resolution_action"] == action
    assert resolved["resolved_at"] == decided_at
    assert resolved["resolved_by"] == test_db.execute(
        "SELECT name FROM actors WHERE id=%s", (owner,)
    ).fetchone()[0]
    assert resolved["actions"] == []
    assert resolved["can_act"] is False


def test_run_list_exposes_settlement_marker_without_claiming_success(test_db):
    create_decision_request_tables(test_db)
    _seed_run_awaiting_approval(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='complete', settling_at=%s "
        "WHERE id=%s",
        ("2026-07-26T01:00:00Z", RUN_ID),
    )
    test_db.commit()

    row = next(row for row in list_deployment_runs(
        project=None, status=None, limit=100,
    ) if row["id"] == RUN_ID)
    assert row["settling_at"] == "2026-07-26T01:00:00Z"
    assert row["current_stage"] == "complete"
    assert row["status"] == "executing"


def test_a_halted_run_shows_screenshots_attached_after_the_gate_was_recorded(test_db):
    create_decision_request_tables(test_db)
    owner, _originator = _seed_run_awaiting_approval(test_db)

    # The gate froze with nothing to attach; qa tables did not exist yet.
    frozen = run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID][0]
    assert frozen["subject_context"]["evidence"]["state"] == "absent"

    create_qa_catalog_tables(test_db)
    requirement_id = test_db.execute(
        "INSERT INTO qa_requirements "
        "(deployment_run_id, method_id, method_name, expected_outcome, "
        "runner_id, verdict_path, qa_kind, qa_phase, blocking_mode, "
        "created_at) VALUES (%s, 'browser-inspection', 'Browser inspection', "
        "'The release renders.', 'browser_substrate', 'agent', 'plan_case', "
        "'post_deploy', 'blocking', '2026-07-26T00:00:00Z') RETURNING id",
        (RUN_ID,),
    ).fetchone()[0]
    run_row_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, raw_result, "
        "created_at) VALUES (%s, 'agent', 'manual_acceptance', 'pass', %s, "
        "'2026-07-26T00:00:00Z') RETURNING id",
        (requirement_id, json.dumps({"release_lineage": "lineage-gate-proof"})),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle, created_at) "
        "VALUES (%s, 'screenshot', %s, '2026-07-26T00:00:00Z')",
        (run_row_id, '{"backend":"local","path":"/tmp/run-gate-evidence.png"}'),
    )
    test_db.commit()

    gate = run_gates(test_db, [RUN_ID], actor_id=owner)[RUN_ID][0]
    # A still-pending gate's returned evidence recomputes against the same
    # subject and revision, so it now sees what was attached since it froze.
    evidence = gate["subject_context"]["evidence"]
    assert evidence["screenshot_count"] == 1
    assert evidence["expected_revision"] == "lineage-gate-proof"
    # The stored row is never rewritten -- only the returned copy changes.
    stored = json.loads(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE subject_key LIKE %s",
            (f"{RUN_ID}:%",),
        ).fetchone()[0]
    )
    assert stored["evidence"]["state"] == "absent"
    assert stored["evidence"]["screenshot_count"] == 0
