"""Runner-wide secret redaction for locally submitted Machine QA results."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import machine_qa_local_execution
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.machine_qa_execution_contract import issue_execution_contract
from runtime.api.domain.qa_plan_execution_test_support import (
    synthetic_execution_target,
)


def test_fixture_augmented_evidence_is_redacted_before_submission(monkeypatch):
    secret = "credential-that-must-not-leave-the-client"
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={"ssh_private_key": secret}),
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "_execution",
        lambda _contract: execution,
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "execute_case_with_fixture_lifecycle",
        lambda _execution, _case: MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence={
                "runner_id": "host_control",
                "fixture_report": f"prepared with {secret}",
            },
        ),
    )
    execution_target, execution_target_digest = synthetic_execution_target(
        project_id=4,
        project="yoke",
    )
    case = {
        "requirement_id": 1,
        "item_id": 2,
        "plan_id": 3,
        "case_key": "secret-redaction",
        "method_id": "machine-state-check",
        "method_name": "Machine state check",
        "runner_id": "host_control",
        "required_capability_kind": "test-machine",
        "verdict_path": "automatic",
        "qa_kind": "machine",
        "instructions": "Check the machine.",
        "expected_outcome": "The machine is ready.",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        "host_baseline": None,
        "entry_surface": None,
        "required_completion": None,
        "workflow_transition_id": "implemented",
        "project_id": 4,
        "project": "yoke",
        "execution_target": execution_target,
        "execution_target_digest": execution_target_digest,
        "lane_branch": None,
        "case_position": 1,
        "baseline_position": 1,
    }
    contract = issue_execution_contract(
        operation="case",
        lease_id=5,
        lease_key="test-machine:mac",
        project_id=4,
        project="yoke",
        settings={
            "resource_name": "test-mac",
            "host": "test-mac.local",
            "user": "tester",
            "operating_notes": "",
        },
        cases=[case],
    )

    submission = machine_qa_local_execution.execute_machine_case_contract(
        contract.model_dump(mode="json")
    )

    assert secret not in repr(submission.payload)
    assert (
        submission.payload["results"][0]["evidence"]["fixture_report"]
        == "prepared with [REDACTED]"
    )
