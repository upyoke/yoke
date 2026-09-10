"""Primary-action exception evidence for the Machine QA fixture lifecycle."""

from __future__ import annotations

from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
    action_result,
    run_lifecycle,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError


def test_primary_exception_keeps_named_cause_and_runs_cleanup() -> None:
    result, execution, events = run_lifecycle(
        primary_error=RuntimeError("terminal recipe aborted")
    )
    action = result.evidence["primary_action"]

    assert result.error_code == "machine_method_failed"
    assert execution.execute_calls == 1
    assert events == ["setup", "primary", "close"]
    assert action["outcome"] == "failed"
    assert action["reason"] == "machine_method_failed"
    assert "repair that host operation" in action["recovery"]
    assert "RuntimeError: terminal recipe aborted" in action["diagnostic"]
    assert result.evidence["fixture_operations"]["setup"]["operations"]


def test_cleanup_after_primary_exception_still_closes_the_fixture() -> None:
    result, _execution, events = run_lifecycle(
        primary_error=RuntimeError("terminal recipe aborted"),
        cleanup=[action_result(True, "fixture.yoke-api-start")],
    )

    assert events == ["setup", "primary", "close"]
    assert result.evidence["fixture_operations"]["cleanup_attempts"] == [
        {
            "outcome": "passed",
            "operations": [{"id": "fixture.yoke-api-start", "outcome": "passed"}],
        }
    ]
    assert result.evidence["primary_action"]["reason"] == "machine_method_failed"


def test_combined_failures_keep_primary_cause_under_cleanup_precedence() -> None:
    failed_cleanup = action_result(False, "fixture.yoke-api-start")
    result, _execution, events = run_lifecycle(
        primary_error=RuntimeError("terminal recipe aborted"),
        cleanup=[failed_cleanup, failed_cleanup],
    )
    action = result.evidence["primary_action"]

    assert result.error_code == "fixture_cleanup_failed"
    assert events == ["setup", "primary", "close", "close"]
    assert action["reason"] == "machine_method_failed"
    assert "terminal recipe aborted" in action["diagnostic"]
    assert result.evidence["fixture_operations"]["cleanup_attempts"][0]["outcome"] == (
        "failed"
    )


def test_primary_exception_evidence_is_secret_safe() -> None:
    secret = "credential-that-must-not-leave-the-client"
    result, _execution, _events = run_lifecycle(
        primary_error=HostControlLocalError(
            code="host_control_connection_failed",
            phase="host_facts_ssh",
            detail=f"SSH failed with {secret}",
            stderr=f"Permission denied {secret}",
            recovery_hint="Check network reachability and SSH authorization.",
        ),
        secrets={"ssh_private_key": secret},
    )
    action = result.evidence["primary_action"]

    assert secret not in str(result.evidence)
    assert action["reason"] == "host_control_connection_failed"
    assert "SSH authorization" in action["recovery"]
    assert "[REDACTED]" in action["diagnostic"]
    assert "Permission denied" in action["diagnostic"]
