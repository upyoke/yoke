"""Deployment approval requests preserve run state until the runner consumes them."""

from __future__ import annotations

import json

import pytest

from runtime.api.deployment_stage_approval_fixture import (
    OpenConnection,
    seed_stage_approval,
)
from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.decision_request_schema import (
    create_decision_request_tables,
)
from yoke_core.domain import deployment_run_approval
from yoke_core.domain import control_plane_transport
from yoke_core.domain.deployment_approval_requests import (
    emit_deployment_completion,
    deployment_stage_decision,
    deployment_stage_is_approved,
    evaluate_deployment_stage_approval,
)
from yoke_core.domain.deployment_stage_approval_dispatch import (
    dispatch_deployment_stage_approval,
)


def _serving_verdict(conn, run_id: str, stage: str) -> dict:
    """Answer as the build serving this control plane would."""
    verdict = evaluate_deployment_stage_approval(
        conn,
        run_id=run_id,
        stage=stage,
    )
    return {
        "run_id": run_id,
        "stage": stage,
        "satisfied": bool(verdict.satisfied),
        "request_id": int(verdict.request_id),
        "request_status": str(verdict.request_status),
        "resolution_action": verdict.resolution_action,
        "reason": str(verdict.reason),
    }


def _prod_environment_id(conn) -> int:
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Approval test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Approval test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
        ).fetchone()[0]
    )


def test_deployment_stage_request_is_idempotent_and_runner_consumable(
    test_db,
    monkeypatch,
):
    seeded = seed_stage_approval(test_db)
    originator = seeded["originator"]
    owner = seeded["owner"]
    member = seeded["member"]

    first = evaluate_deployment_stage_approval(
        test_db,
        run_id="run-approval-proof",
        stage=seeded["stage"],
        originator_actor_id=originator,
    )
    repeated = evaluate_deployment_stage_approval(
        test_db,
        run_id="run-approval-proof",
        stage=seeded["stage"],
        originator_actor_id=originator,
    )
    assert first.satisfied is False
    assert first.request_status == "pending"
    assert repeated.request_id == first.request_id
    request_id = first.request_id
    context = json.loads(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s",
            (request_id,),
        ).fetchone()[0]
    )
    member_ref = format_item_ref(member[3], member[4], member[1])
    assert context == {
        "run_id": "run-approval-proof",
        "flow": {"id": "approval-proof", "name": "Approval proof"},
        "stage": "approve-prod",
        "batch": {
            "item_count": 1,
            "items": [
                {
                    "item_id": int(member[0]),
                    "item_ref": member_ref,
                    "title": str(member[2]),
                }
            ],
        },
        "shipping": {
            "release_lineage": "release-proof-lineage",
            "target_environment": "prod",
            "summary": (
                "1 item(s) ship to prod under release lineage release-proof-lineage."
            ),
        },
        # What the release actually carries, derived once when the request
        # was created. This run has no predecessor to measure against, and
        # the snapshot says exactly that rather than implying an empty
        # release.
        "stage_position": {"index": 0, "total": 2, "remaining": ["release"]},
        "carried": {
            "schema": 1,
            "derivation": {
                "status": "empty",
                # The comparison could not run — there is no predecessor —
                # which is a different fact from a release that carries
                # nothing, and the reader must not conflate them.
                "contents_known": False,
                "reason": "no_prior_succeeded_run",
                "recovery": (
                    "No action is required; this run establishes the lineage baseline."
                ),
                "run_id": "run-approval-proof",
                "previous_run_id": "",
                "previous_release_lineage": "",
                "release_lineage": "release-proof-lineage",
            },
            "items": [],
            "commits": [],
            "warnings": [],
        },
        # Every stage of this flow runs an allowlisted runner, and the batch
        # is one item — yet it names prod and cannot prove what it carries,
        # so it is a release. Benign-looking runners alone never make a
        # practice gate.
        "release_effect": {
            "deploys": True,
            "headline": "Deploy to prod — approve the approve-prod stage",
            "effect": "",
            "basis": [
                "The flow targets prod.",
                "This run carries linked work items.",
            ],
        },
        "title": "Deploy to prod — approve the approve-prod stage",
    }
    assert (
        deployment_stage_is_approved(
            test_db,
            run_id="run-approval-proof",
            stage_id="approve-prod",
        )
        is False
    )
    assert (
        deployment_stage_decision(
            test_db,
            run_id="run-approval-proof",
            stage_id="approve-prod",
        )
        is None
    )
    assert (
        test_db.execute(
            "SELECT current_stage FROM deployment_runs WHERE id='run-approval-proof'"
        ).fetchone()[0]
        == "approve-prod"
    )

    open_conn = OpenConnection(test_db)
    import yoke_core.domain.db_helpers as db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: open_conn)
    # The pipeline asks the serving build rather than deriving the verdict
    # itself; standing in for that build here keeps the end-to-end shape.
    monkeypatch.setattr(
        control_plane_transport,
        "serving_authority",
        lambda function_id, payload, target=None: _serving_verdict(
            test_db,
            target.workflow_run_id,
            payload["stage"],
        ),
    )
    assert dispatch_deployment_stage_approval(
        "run-approval-proof",
        "approve-prod",
    ) == (-2, "")

    monkeypatch.setattr(
        deployment_run_approval,
        "connect",
        lambda: open_conn,
    )
    approval = deployment_run_approval.approve_run(
        "run-approval-proof",
        actor_id=owner,
        session_id="approval-session",
        note="prod checks passed",
    )
    assert approval.decision_request_id == request_id
    assert approval.next_stage == "release"
    assert approval.stage_approved is True
    assert (
        deployment_stage_is_approved(
            test_db,
            run_id="run-approval-proof",
            stage_id="approve-prod",
        )
        is True
    )
    assert (
        deployment_stage_decision(
            test_db,
            run_id="run-approval-proof",
            stage_id="approve-prod",
        )
        == "approve"
    )
    assert dispatch_deployment_stage_approval(
        "run-approval-proof",
        "approve-prod",
    ) == (0, "")
    assert (
        test_db.execute(
            "SELECT current_stage FROM deployment_runs WHERE id='run-approval-proof'"
        ).fetchone()[0]
        == "approve-prod"
    )


def test_deployment_completion_event_shares_the_caller_transaction(
    test_db,
):
    create_decision_request_tables(test_db)
    environment_id = _prod_environment_id(test_db)
    initiator = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES ('completion-proof', 1, 'Completion proof', '[]', "
        "'2026-07-26T00:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, created_by, created_at) "
        "VALUES ('run-completion-proof', 1, 'completion-proof', 'persistent', "
        "%s, 'succeeded', %s, '2026-07-26T00:00:00Z')",
        (environment_id, str(initiator)),
    )
    test_db.commit()

    emit_deployment_completion(
        test_db,
        run_id="run-completion-proof",
        event_name="DeploymentRunSucceeded",
        outcome="completed",
        context={"flow": "completion-proof"},
    )
    recorded = "SELECT COUNT(*) FROM events WHERE event_name=%s"
    assert test_db.execute(recorded, ("DeploymentRunSucceeded",)).fetchone()[0] == 1
    test_db.rollback()
    assert test_db.execute(recorded, ("DeploymentRunSucceeded",)).fetchone()[0] == 0


def test_terminal_deployment_telemetry_cannot_fail_the_pipeline(test_db):
    # deployment_runs already owns the terminal outcome by the time the
    # pipeline emits, so an events outage must not surface as the run's
    # own failure. Dropping the table is the harshest stand-in for one.
    create_decision_request_tables(test_db)
    environment_id = _prod_environment_id(test_db)
    initiator = int(
        test_db.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES ('telemetry-outage', 1, 'Telemetry outage', '[]', "
        "'2026-07-26T00:00:00Z')"
    )
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, created_by, created_at) "
        "VALUES ('run-telemetry-outage', 1, 'telemetry-outage', 'persistent', "
        "%s, 'succeeded', %s, '2026-07-26T00:00:00Z')",
        (environment_id, str(initiator)),
    )
    test_db.commit()
    test_db.execute("DROP TABLE events CASCADE")

    emit_deployment_completion(
        test_db,
        run_id="run-telemetry-outage",
        event_name="DeploymentRunSucceeded",
        outcome="completed",
        context={"flow": "telemetry-outage"},
    )

    # The savepoint kept the transaction usable, so the caller can still
    # commit the work the terminal event was only describing.
    test_db.commit()
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id='run-telemetry-outage'"
        ).fetchone()[0]
        == "succeeded"
    )


def test_an_unknown_completion_event_name_still_raises(test_db):
    with pytest.raises(ValueError, match="not a deployment completion event"):
        emit_deployment_completion(
            test_db,
            run_id="run-telemetry-outage",
            event_name="DeploymentRunFinished",
            outcome="completed",
            context={},
        )
