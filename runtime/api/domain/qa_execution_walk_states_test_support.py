# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import importlib

import base64

import json

from unittest.mock import patch

import pytest

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review

from yoke_core.domain import db_backend

from yoke_core.domain.agent_mission_restore import (
    commit_mission_handback,
    post_capture_state,
)

from yoke_core.domain.migration_serving_version import NEXT_RELEASE

from yoke_core.domain.qa_plan_execution_store import lock_plan_execution, roster_digest


def record_handback(actor, requirement_id, run_id):
    from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
    from yoke_core.domain.qa_artifact_recording import handle_qa_artifact_add

    outcome = handle_qa_artifact_add(
        FunctionCallRequest(
            function="qa.artifact.add",
            actor=actor,
            target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
            payload={
                "run_id": run_id,
                "artifact_type": "starting_state_restore",
                "content_type": "application/json",
                "filename": "restore.json",
                "content_base64": base64.b64encode(
                    json.dumps(
                        {
                            "restored": True,
                            "baseline": "fresh-host",
                        }
                    ).encode()
                ).decode(),
            },
        )
    )
    assert outcome.primary_success, outcome.error


def assert_walking_proof(conn, execution):
    from yoke_core.domain.qa_plan_case_proof import _case_result

    case = execution["roster"][0]
    proof = _case_result(
        conn,
        plan_id=case["plan_id"],
        case_key=case["case_key"],
        host_baseline=case["host_baseline"],
        deployment_run_id=None,
    )
    assert execution["state"] == proof["review"]["state"] == "walking"
    assert proof["review"]["capture_runner"] == "agent_mission"
