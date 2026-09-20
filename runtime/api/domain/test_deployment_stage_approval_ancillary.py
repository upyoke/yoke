"""Human approval is per run stage, including ancillary carrying runs.

An already-done member riding another flow still waits at that run's own
gate. Rejecting it closes that run and does not reopen the item. A later
ancillary run is a new ``run_id:stage`` subject and needs a fresh decision.
"""

from __future__ import annotations

from runtime.api.deployment_stage_approval_fixture import (
    seed_gate_run,
)
from runtime.api.domain.test_deployment_stage_approval_operation import (
    _evaluate,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)


def _owner_authority(test_db):
    owner = int(
        test_db.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    )
    role = int(
        test_db.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (9511, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
            "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
            "RETURNING id"
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') ON CONFLICT DO NOTHING",
        (owner, role),
    )
    test_db.commit()
    return owner


def _done_member(test_db, item_id, *, completion_flow):
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="done",
        deployment_flow=completion_flow,
    )


def _carry(test_db, run_id, item_id):
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, '2026-09-17T00:00:00Z')",
        (run_id, item_id),
    )
    test_db.commit()


def _item_status(test_db, item_id):
    return str(
        test_db.execute(
            "SELECT status FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _run_status(test_db, run_id):
    return str(
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
    )


def _resolution(test_db, request_id):
    return str(
        test_db.execute(
            "SELECT resolution_action FROM decision_requests WHERE id = %s",
            (request_id,),
        ).fetchone()[0]
    )


def _selected_and_ancillary(test_db, *, selected_flow, selected_run, ancillary_flow,
                            ancillary_run):
    create_decision_request_tables(test_db)
    seed_gate_run(
        test_db,
        flow_id=selected_flow,
        run_id=selected_run,
        stages_json='[{"name":"release","step_runner":"auto"}]',
        current_stage="release",
    )
    seed_gate_run(
        test_db,
        flow_id=ancillary_flow,
        run_id=ancillary_run,
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )


def test_an_ancillary_run_still_waits_on_its_own_human_approval(
    test_db, monkeypatch,
):
    _selected_and_ancillary(
        test_db,
        selected_flow="gate-selected",
        selected_run="run-gate-selected",
        ancillary_flow="gate-ancillary",
        ancillary_run="run-gate-ancillary",
    )
    _done_member(test_db, 9620, completion_flow="gate-selected")
    _carry(test_db, "run-gate-ancillary", 9620)
    outcome = _evaluate(
        test_db, monkeypatch, "run-gate-ancillary", "approve-prod",
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["satisfied"] is False
    assert outcome.result_payload["request_status"] == "pending"
    assert outcome.result_payload["request_id"] > 0
    assert _item_status(test_db, 9620) == "done"


def test_rejecting_an_ancillary_gate_does_not_reopen_a_done_item(
    test_db, monkeypatch,
):
    owner = _owner_authority(test_db)
    _selected_and_ancillary(
        test_db,
        selected_flow="gate-selected-stay",
        selected_run="run-gate-selected-stay",
        ancillary_flow="gate-ancillary-reject",
        ancillary_run="run-gate-ancillary-reject",
    )
    _done_member(test_db, 9621, completion_flow="gate-selected-stay")
    _carry(test_db, "run-gate-ancillary-reject", 9621)
    pending = _evaluate(
        test_db, monkeypatch, "run-gate-ancillary-reject", "approve-prod",
    )
    resolve_decision_request(
        test_db,
        pending.result_payload["request_id"],
        actor_id=owner,
        action="reject",
        session_id="gate-session",
    )
    test_db.commit()
    # The rejection closes the carrying run, because a rejected stage has
    # nothing left to advance. The member it carried is somebody else's
    # completed work and is left exactly as it was.
    assert _run_status(test_db, "run-gate-ancillary-reject") == "failed"
    assert _resolution(test_db, pending.result_payload["request_id"]) == "reject"
    assert _item_status(test_db, 9621) == "done"


def test_an_already_done_member_needs_a_fresh_approval_on_a_new_ancillary_run(
    test_db, monkeypatch,
):
    owner = _owner_authority(test_db)
    _selected_and_ancillary(
        test_db,
        selected_flow="gate-selected-done",
        selected_run="run-gate-selected-done",
        ancillary_flow="gate-ancillary-first",
        ancillary_run="run-gate-ancillary-first",
    )
    seed_gate_run(
        test_db,
        flow_id="gate-ancillary-second",
        run_id="run-gate-ancillary-second",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )
    _done_member(test_db, 9622, completion_flow="gate-selected-done")
    _carry(test_db, "run-gate-ancillary-first", 9622)
    _carry(test_db, "run-gate-ancillary-second", 9622)
    first = _evaluate(
        test_db, monkeypatch, "run-gate-ancillary-first", "approve-prod",
    )
    resolve_decision_request(
        test_db,
        first.result_payload["request_id"],
        actor_id=owner,
        action="approve",
        session_id="gate-session",
    )
    test_db.commit()
    second = _evaluate(
        test_db, monkeypatch, "run-gate-ancillary-second", "approve-prod",
    )
    assert second.result_payload["satisfied"] is False
    assert second.result_payload["request_status"] == "pending"
    assert second.result_payload["request_id"] != first.result_payload["request_id"]
    assert _item_status(test_db, 9622) == "done"
