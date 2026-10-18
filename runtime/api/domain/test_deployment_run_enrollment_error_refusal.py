"""An enrollment that stops at one item names that item when others go missing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_run_carried_membership import (
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_enrollment_error import CarriedEnrollmentError
from yoke_core.domain.flow_create import cmd_create


FLOW = "enrollment-error-flow"
ITEM_ID = 9601


def _candidate(conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A created run whose candidate carries one landed, deliverable item."""
    stage_environment(conn)
    cmd_create(
        conn,
        FLOW,
        "yoke",
        "Release admission",
        "",
        json.dumps(
            [
                {
                    "name": "deploy",
                    "step_runner": "auto",
                    "stage_kind": "execution",
                    "scope": "run",
                },
                {
                    "name": "item-qa",
                    "step_runner": "qa",
                    "stage_kind": "qa",
                    "scope": "item",
                    "target": {
                        "kind": "persistent_environment",
                        "environment": "stage",
                        "source_stage": "deploy",
                    },
                    "verdict": {"mode": "agent_only"},
                },
            ]
        ),
        status="disabled",
    )
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=FLOW,
    )
    ref = item_ref(conn, ITEM_ID)
    repo, baseline, tip = release_repository(tmp_path, ref)
    record_landing_receipt(conn, ITEM_ID, branch=ref, tip=tip)
    serve_repository(monkeypatch, repo)
    insert_run(conn, "run-previous", lineage=baseline, status="succeeded", flow=FLOW)
    insert_run(conn, "run-candidate", lineage=tip, status="created", flow=FLOW)
    return ref


def test_omission_names_the_item_and_cause_where_enrollment_stopped(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _candidate(test_db, tmp_path, monkeypatch)
    requirement = insert_qa_requirement(
        test_db,
        item_id=ITEM_ID,
        qa_phase="post_deploy",
        target_env="stage",
        success_policy="Workflow completes with conclusion=success",
    )
    test_db.commit()

    with pytest.raises(CarriedEnrollmentError) as stopped:
        enroll_carried_members(test_db, "run-candidate")

    error = stopped.value
    assert error.item_ref == ref
    assert "qa_success_policy_unreadable" in error.cause
    assert f"--requirement-id {requirement['id']}" in error.cause
    assert "Expecting value" not in str(error)

    refusal = carried_membership_refusal(
        test_db, "run-candidate", enrollment_error=error
    )

    assert refusal is not None
    assert f"enrollment stopped at {ref}, which it could not admit" in refusal
    assert "qa_success_policy_unreadable" in refusal
    assert "became deliverable after this run composed" not in refusal


def test_omission_without_an_enrollment_error_keeps_the_composition_reason(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(test_db, tmp_path, monkeypatch)

    refusal = carried_membership_refusal(test_db, "run-candidate")

    assert refusal is not None
    assert "became deliverable after this run composed its membership" in refusal
