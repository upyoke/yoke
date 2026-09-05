"""What a halted run reports, and to whom it offers the answer."""

from __future__ import annotations

from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_run_gates import run_gates

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
