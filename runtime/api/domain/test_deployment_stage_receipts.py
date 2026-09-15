"""Deployment-stage receipt attempts remain ordered, exact, and fail closed."""

from __future__ import annotations

import json
from typing import Any

import pytest

from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
    deployment_stage_receipt_for_qa,
)


LINEAGE = "d" * 40


def _seed(conn: Any, run_id: str, *, artifact_identity: str | None = None) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,'stage','https://stage.example.test','{}',%s FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        ("2026-09-14T00:00:00Z",),
    )
    stages = [
        {
            "name": "deploy-stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "release-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "run",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy-stage",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
    flow_id = f"flow-{run_id}"
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(stages),
        status="disabled",
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,artifact_identity,created_at) "
        "VALUES (%s,1,%s,%s,'executing','deploy-stage',%s,%s)",
        (
            run_id,
            flow_id,
            LINEAGE,
            artifact_identity,
            "2026-09-14T00:00:00Z",
        ),
    )
    conn.commit()


def _allocate(conn: Any, run_id: str, correlation: str) -> dict[str, Any]:
    return allocate_deployment_stage_receipt(
        conn,
        run_id=run_id,
        stage_name="deploy-stage",
        correlation_id=correlation,
        target_kind="persistent_environment",
        executor="test-runner",
    )


def _complete_ready(conn: Any, run_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    return complete_deployment_stage_receipt(
        conn,
        run_id=run_id,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://stage.example.test/",
        observed_release_lineage=LINEAGE,
        executor_receipt=f"executor://{receipt['correlation_id']}",
    )


def test_allocation_is_ordered_and_same_correlation_is_idempotent(test_db) -> None:
    _seed(test_db, "run-receipt-allocation")
    first = _allocate(test_db, "run-receipt-allocation", "dispatch-1")
    replay = _allocate(test_db, "run-receipt-allocation", "dispatch-1")
    second = _allocate(test_db, "run-receipt-allocation", "dispatch-2")

    assert replay["id"] == first["id"]
    assert (first["attempt_number"], second["attempt_number"]) == (1, 2)
    with pytest.raises(ValueError, match="different immutable dispatch inputs"):
        allocate_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-allocation",
            stage_name="deploy-stage",
            correlation_id="dispatch-1",
            target_kind="run_preview",
            executor="test-runner",
        )


def test_late_older_success_cannot_replace_newer_failed_attempt(test_db) -> None:
    _seed(test_db, "run-receipt-order")
    older = _allocate(test_db, "run-receipt-order", "dispatch-older")
    newer = _allocate(test_db, "run-receipt-order", "dispatch-newer")
    complete_deployment_stage_receipt(
        test_db,
        run_id="run-receipt-order",
        receipt_id=int(newer["id"]),
        correlation_id="dispatch-newer",
        status="failed",
        failure_reason="health observation failed; retry the deploy stage",
    )
    _complete_ready(test_db, "run-receipt-order", older)

    with pytest.raises(ValueError, match="latest deployment stage receipt is 'failed'"):
        deployment_stage_receipt_for_qa(
            test_db,
            run_id="run-receipt-order",
            source_stage="deploy-stage",
            expected_target_kind="persistent_environment",
            expected_target_name="stage",
            expected_release_lineage=LINEAGE,
        )


def test_completion_is_idempotent_but_conflicting_callback_is_refused(test_db) -> None:
    _seed(test_db, "run-receipt-callback")
    receipt = _allocate(test_db, "run-receipt-callback", "dispatch-once")
    completed = _complete_ready(test_db, "run-receipt-callback", receipt)
    replay = _complete_ready(test_db, "run-receipt-callback", receipt)
    assert replay["id"] == completed["id"]

    with pytest.raises(ValueError, match="already terminal with different evidence"):
        complete_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-callback",
            receipt_id=int(receipt["id"]),
            correlation_id="dispatch-once",
            status="ready",
            target_name="stage",
            observed_url="https://other.example.test",
            observed_release_lineage=LINEAGE,
        )


def test_ready_receipt_requires_exact_candidate_and_target(test_db) -> None:
    _seed(test_db, "run-receipt-exact")
    receipt = _allocate(test_db, "run-receipt-exact", "dispatch-exact")
    with pytest.raises(ValueError, match="different release lineage"):
        complete_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-exact",
            receipt_id=int(receipt["id"]),
            correlation_id="dispatch-exact",
            status="ready",
            target_name="stage",
            observed_release_lineage="e" * 40,
        )
    completed = _complete_ready(test_db, "run-receipt-exact", receipt)
    with pytest.raises(ValueError, match="target does not match"):
        deployment_stage_receipt_for_qa(
            test_db,
            run_id="run-receipt-exact",
            source_stage="deploy-stage",
            expected_target_kind="persistent_environment",
            expected_target_name="prod",
            expected_release_lineage=LINEAGE,
        )
    selected = deployment_stage_receipt_for_qa(
        test_db,
        run_id="run-receipt-exact",
        source_stage="deploy-stage",
        expected_target_kind="persistent_environment",
        expected_target_name="stage",
        expected_release_lineage=LINEAGE,
        receipt_id=int(completed["id"]),
    )
    assert selected["observed_url"] == "https://stage.example.test"


def test_ready_receipt_requires_the_run_artifact_when_one_is_pinned(test_db) -> None:
    artifact = '{"digest":"sha256:pinned"}'
    _seed(test_db, "run-receipt-artifact", artifact_identity=artifact)
    receipt = _allocate(test_db, "run-receipt-artifact", "dispatch-artifact")
    with pytest.raises(ValueError, match="different artifact identity"):
        complete_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-artifact",
            receipt_id=int(receipt["id"]),
            correlation_id="dispatch-artifact",
            status="ready",
            target_name="stage",
            observed_release_lineage=LINEAGE,
            observed_artifact_identity='{"digest":"sha256:other"}',
        )
    completed = complete_deployment_stage_receipt(
        test_db,
        run_id="run-receipt-artifact",
        receipt_id=int(receipt["id"]),
        correlation_id="dispatch-artifact",
        status="ready",
        target_name="stage",
        observed_release_lineage=LINEAGE,
        observed_artifact_identity=artifact,
    )
    selected = deployment_stage_receipt_for_qa(
        test_db,
        run_id="run-receipt-artifact",
        source_stage="deploy-stage",
        expected_target_kind="persistent_environment",
        expected_target_name="stage",
        expected_release_lineage=LINEAGE,
        expected_artifact_identity=artifact,
        receipt_id=int(completed["id"]),
    )
    assert selected["observed_artifact_identity"] == artifact
    with pytest.raises(ValueError, match="artifact differs"):
        deployment_stage_receipt_for_qa(
            test_db,
            run_id="run-receipt-artifact",
            source_stage="deploy-stage",
            expected_target_kind="persistent_environment",
            expected_target_name="stage",
            expected_release_lineage=LINEAGE,
            expected_artifact_identity='{"digest":"sha256:other"}',
        )


def test_superseded_ready_receipt_cannot_revalidate_qa(test_db) -> None:
    _seed(test_db, "run-receipt-superseded")
    first = _allocate(test_db, "run-receipt-superseded", "dispatch-first")
    _complete_ready(test_db, "run-receipt-superseded", first)
    _allocate(test_db, "run-receipt-superseded", "dispatch-replacement")

    with pytest.raises(ValueError, match="superseded by a newer attempt"):
        deployment_stage_receipt_for_qa(
            test_db,
            run_id="run-receipt-superseded",
            source_stage="deploy-stage",
            expected_target_kind="persistent_environment",
            expected_target_name="stage",
            expected_release_lineage=LINEAGE,
            receipt_id=int(first["id"]),
        )


def test_completion_refuses_a_receipt_from_a_different_run(test_db) -> None:
    _seed(test_db, "run-receipt-owner-a")
    _seed(test_db, "run-receipt-owner-b")
    receipt = _allocate(test_db, "run-receipt-owner-a", "dispatch-owner")

    with pytest.raises(ValueError, match="does not belong to the authorized run"):
        complete_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-owner-b",
            receipt_id=int(receipt["id"]),
            correlation_id="dispatch-owner",
            status="ready",
            target_name="stage",
            observed_release_lineage=LINEAGE,
        )


def test_completion_refuses_once_the_run_is_no_longer_executing(test_db) -> None:
    _seed(test_db, "run-receipt-cancelled")
    receipt = _allocate(test_db, "run-receipt-cancelled", "dispatch-cancelled")
    test_db.execute(
        "UPDATE deployment_runs SET status='cancelled' WHERE id=%s",
        ("run-receipt-cancelled",),
    )
    test_db.commit()

    with pytest.raises(ValueError, match="no longer executing"):
        complete_deployment_stage_receipt(
            test_db,
            run_id="run-receipt-cancelled",
            receipt_id=int(receipt["id"]),
            correlation_id="dispatch-cancelled",
            status="ready",
            target_name="stage",
            observed_release_lineage=LINEAGE,
        )
