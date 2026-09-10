"""The registered exact-run/exact-stage approval verdict, server-side.

The build serving a control plane is the only one whose columns match that
database, so the verdict is derived here rather than in whatever revision a
caller happens to be running. These tests cover both target environments and
both gate shapes — a role and a named person — because the named-person path
is the one that reads a person's name and so the one a schema change breaks.
"""

from __future__ import annotations

import pytest

from runtime.api.deployment_stage_approval_fixture import (
    OpenConnection,
    seed_gate_run,
)
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)


def _evaluate_request(run_id: str, stage: str, *, actor_id=None):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.deployment_approval_requests import (
        EVALUATE_STAGE_APPROVAL_FUNCTION,
    )

    return FunctionCallRequest(
        function=EVALUATE_STAGE_APPROVAL_FUNCTION,
        actor=ActorContext(actor_id=actor_id, session_id="gate-session"),
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"stage": stage},
    )


def _evaluate(test_db, monkeypatch, run_id, stage, *, actor_id=None):
    """Drive the registered operation the way the serving build runs it."""
    import yoke_core.domain.db_helpers as db_helpers
    from yoke_core.domain.handlers import deployment_stage_approval

    monkeypatch.setattr(
        db_helpers,
        "connect",
        lambda: OpenConnection(test_db),
    )
    return deployment_stage_approval.handle_deployment_stage_approval_evaluate(
        _evaluate_request(run_id, stage, actor_id=actor_id)
    )


def test_a_stage_the_run_is_not_waiting_at_is_refused(test_db):
    """The caller names the gate it means; the run does not choose for it."""
    create_decision_request_tables(test_db)
    seed_gate_run(
        test_db,
        flow_id="gate-exact",
        run_id="run-gate-exact",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}},'
            '{"name":"approve-result","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )
    with pytest.raises(ValueError) as raised:
        evaluate_deployment_stage_approval(
            test_db,
            run_id="run-gate-exact",
            stage="approve-result",
        )
    message = str(raised.value)
    assert "approve-prod" in message
    assert "approve-result" in message
    assert (
        test_db.execute(
            "SELECT count(*) FROM decision_requests "
            "WHERE subject_type='deployment_stage'"
        ).fetchone()[0]
        == 0
    )


def test_the_registered_operation_reports_a_prod_role_gate_as_waiting(
    test_db,
    monkeypatch,
):
    create_decision_request_tables(test_db)
    seed_gate_run(
        test_db,
        flow_id="gate-op-prod",
        run_id="run-gate-op-prod",
        environment="prod",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )
    outcome = _evaluate(test_db, monkeypatch, "run-gate-op-prod", "approve-prod")
    assert outcome.primary_success is True
    assert outcome.result_payload["satisfied"] is False
    assert outcome.result_payload["stage"] == "approve-prod"
    assert outcome.result_payload["request_status"] == "pending"
    assert outcome.result_payload["request_id"] > 0


def test_the_registered_operation_reports_a_stage_named_person_gate(
    test_db,
    monkeypatch,
):
    """The gate shape that crashed a release: a named person, not a role."""
    create_decision_request_tables(test_db)
    actor = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    seed_gate_run(
        test_db,
        flow_id="gate-op-stage",
        run_id="run-gate-op-stage",
        environment="stage",
        current_stage="approve-release",
        stages_json=(
            '[{"name":"approve-release","step_runner":"human-approval",'
            f'"approvals":{{"roles":[],"actors":[{actor}]}}}}]'
        ),
    )
    outcome = _evaluate(
        test_db,
        monkeypatch,
        "run-gate-op-stage",
        "approve-release",
        actor_id=str(actor),
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["satisfied"] is False
    assert outcome.result_payload["stage"] == "approve-release"
    named = [
        int(row[0])
        for row in test_db.execute(
            "SELECT actor_id FROM decision_request_actor_authorities "
            "WHERE request_id=%s",
            (outcome.result_payload["request_id"],),
        ).fetchall()
    ]
    assert named == [actor]


def test_the_registered_operation_reports_a_resolved_gate_as_satisfied(
    test_db,
    monkeypatch,
):
    create_decision_request_tables(test_db)
    owner = int(
        test_db.execute("SELECT id FROM actors ORDER BY id DESC LIMIT 1").fetchone()[0]
    )
    role = int(
        test_db.execute(
            "INSERT INTO roles (id, name, description, created_at) "
            "VALUES (9501, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
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
    seed_gate_run(
        test_db,
        flow_id="gate-op-resolved",
        run_id="run-gate-op-resolved",
        stages_json=(
            '[{"name":"approve-prod","step_runner":"human-approval",'
            '"approvals":{"roles":["owner"],"actors":[]}}]'
        ),
    )
    pending = _evaluate(
        test_db,
        monkeypatch,
        "run-gate-op-resolved",
        "approve-prod",
    )
    resolve_decision_request(
        test_db,
        pending.result_payload["request_id"],
        actor_id=owner,
        action="approve",
        session_id="gate-session",
    )
    test_db.commit()
    satisfied = _evaluate(
        test_db,
        monkeypatch,
        "run-gate-op-resolved",
        "approve-prod",
    )
    assert satisfied.result_payload["satisfied"] is True
    assert satisfied.result_payload["resolution_action"] == "approve"


def test_the_registered_operation_requires_an_exact_stage(test_db, monkeypatch):
    outcome = _evaluate(test_db, monkeypatch, "run-gate-op-prod", "  ")
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
    assert "stages" in outcome.error.message
