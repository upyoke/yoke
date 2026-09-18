"""A Machine QA case accepts every target shape a machine can execute.

The case-authority check was written against one target shape — a plan's
environment snapshot, whose ``environment`` carries a name and nothing else.
A deployment run resolves its own snapshot instead, recording the registered
environment row and the kind of destination beside that name, so every
deployment-scoped host-control case was refused as though its target belonged
to someone else. These cover both halves: the deployment shape executes, and
a target that genuinely disagrees says which field disagrees and what to run.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from yoke_contracts.machine_qa_case_target import (
    MachineQaCaseTargetError,
    case_target_mismatches,
)
from yoke_contracts.machine_qa_execution import (
    MachineQaCaseContract,
    issue_execution_contract,
)

PROJECT_ID = 1
PROJECT = "yoke"
RUN_ID = "run-20260101-001"
MACHINE_SETTINGS = {
    "resource_name": "mac-mini-lab",
    "host": "test-mac.local",
    "user": "yoke-test",
    "host_kind": "mac-ssh",
    "operating_notes": "",
}


def _digest(target: dict) -> str:
    encoded = json.dumps(target, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _environment_target() -> dict:
    return {
        "schema": 2,
        "tenant": {"id": 1, "slug": "upyoke", "name": "Upyoke"},
        "project": {"id": PROJECT_ID, "slug": PROJECT, "name": "Yoke"},
        "site": {"name": "hosted"},
        "environment": {"name": "prod"},
        "endpoints": {"app_url": "https://app.example.test"},
    }


def _deployment_target() -> dict:
    return {
        "schema": 4,
        "target_kind": "deployment",
        "tenant": {"id": 1, "slug": "upyoke", "name": "Upyoke"},
        "project": {"id": PROJECT_ID, "slug": PROJECT, "name": "Yoke"},
        "site": {"name": "hosted"},
        "environment": {"id": 6, "kind": "persistent_environment", "name": "prod"},
        "endpoints": {"app_url": "https://app.example.test"},
        "deployment": {"run_id": RUN_ID, "stage": "item-qa"},
    }


def _case(target: dict, **overrides) -> dict:
    case = {
        "requirement_id": 4321,
        "item_id": None,
        "deployment_run_id": RUN_ID,
        "deployment_stage": "item-qa",
        "deployment_member_item_id": 77,
        "plan_id": 431,
        "case_key": "released-skill-tree-routing",
        "method_id": "terminal-inspection",
        "method_name": "Terminal inspection",
        "runner_id": "host_control",
        "required_capability_kinds": [],
        "verdict_path": "$.verdict",
        "qa_kind": "plan_case",
        "instructions": "look",
        "expected_outcome": "seen",
        "method_config": {},
        "host_baseline": None,
        "entry_surface": None,
        "required_completion": None,
        "workflow_transition_id": None,
        "project_id": PROJECT_ID,
        "project": PROJECT,
        "execution_target": target,
        "execution_target_digest": _digest(target),
        "lane_branch": None,
        "case_position": 1,
        "baseline_position": 1,
    }
    case.update(overrides)
    return case


def test_a_deployment_run_target_is_a_target_a_machine_may_execute() -> None:
    contract = MachineQaCaseContract.model_validate(_case(_deployment_target()))

    assert contract.execution_target["environment"]["kind"] == (
        "persistent_environment"
    )


def test_a_plan_environment_target_still_executes() -> None:
    case = _case(
        _environment_target(),
        deployment_run_id=None,
        deployment_stage=None,
        deployment_member_item_id=None,
        item_id=3400,
    )

    assert MachineQaCaseContract.model_validate(case).item_id == 3400


def test_a_foreign_project_target_names_the_field_and_both_values() -> None:
    target = _deployment_target()
    target["project"] = {"id": 9, "slug": "other", "name": "Other"}

    problems = case_target_mismatches(
        target, project_id=PROJECT_ID, project=PROJECT
    )

    assert any(problem.startswith("project.id: target names 9") for problem in problems)
    assert any(
        problem.startswith("project.slug: target names 'other'")
        for problem in problems
    )


def test_an_unregistered_target_shape_names_the_shapes_that_execute() -> None:
    target = _deployment_target()
    target["schema"] = 99

    problems = case_target_mismatches(
        target, project_id=PROJECT_ID, project=PROJECT
    )

    assert problems == [
        "schema: target declares 99; a Test Machine executes only an "
        "environment target (schema 2) or a deployment target (schema 4)"
    ]


def test_a_refused_deployment_case_names_the_command_that_rebinds_it() -> None:
    target = _deployment_target()
    target["environment"] = {"name": ""}
    case = _case(target)

    with pytest.raises(MachineQaCaseTargetError) as refusal:
        issue_execution_contract(
            operation="case",
            lease_id=1,
            lease_key="test-machine:host",
            project_id=PROJECT_ID,
            project=PROJECT,
            settings=MACHINE_SETTINGS,
            cases=[case],
        )

    message = str(refusal.value)
    assert "environment.name: target names no environment" in message
    assert (
        f"--deployment-run-id {RUN_ID} --stage item-qa --member 77 "
        f"--plan 431 --project {PROJECT}" in message
    )
    # The refusal reads as itself, not as a pydantic dump of the whole case.
    assert "validation error" not in message
    assert "input_value" not in message


def test_an_item_case_refusal_names_the_rematerialize_path() -> None:
    target = _environment_target()
    target["tenant"] = {}
    case = _case(
        target,
        deployment_run_id=None,
        deployment_stage=None,
        deployment_member_item_id=None,
        item_id=3400,
        workflow_transition_id="release",
    )

    with pytest.raises(MachineQaCaseTargetError) as refusal:
        issue_execution_contract(
            operation="case",
            lease_id=1,
            lease_key="test-machine:host",
            project_id=PROJECT_ID,
            project=PROJECT,
            settings=MACHINE_SETTINGS,
            cases=[case],
        )

    message = str(refusal.value)
    assert "tenant.slug: target records no tenant identity" in message
    assert "yoke qa plan rematerialize --item PREFIX-N --transition release" in message
