from __future__ import annotations

from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.host_control_runner import TestMachineMaterial
from yoke_core.domain.machine_qa_execution import MachineQaLease

from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn


def _execution(control: FakeHostControl) -> MachineQaLease:
    conn = make_conn()
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,'test-machine','{}',NULL,'now')"
    )
    return MachineQaLease(
        conn=conn,
        control=control,
        material=TestMachineMaterial(
            project_id=1,
            project="yoke",
            settings={
                "resource_name": "mac-mini-lab",
                "host": "test-mac.local",
                "user": "yoke-test",
                "operating_notes": "",
            },
            secrets={"ssh_private_key": "top-secret"},
        ),
        lease=CoordinationClaim(
            id=4,
            project_id=1,
            lease_key="QA_HOST:mac-mini-lab",
            session_id="session-1",
            acquired_at="now",
        ),
    )


def _execute_assertion(execution: MachineQaLease):
    return execution.execute(
        method_id="machine-state-check",
        method_config={"assertions": [{"argv": ["/usr/bin/true"]}]},
        entry_surface=None,
        required_completion=None,
    )


def test_failed_reset_blocks_case_and_runner_evidence_is_redacted() -> None:
    control = FakeHostControl(refuse_full_reset=True)
    execution = _execution(control)

    assert not execution.reach_baseline("fresh-host").ok
    blocked = _execute_assertion(execution)

    assert blocked.case_outcome == "blocked_on_precondition"
    assert blocked.evidence["case_started"] is False
    assert control.case_calls == 0

    execution.baseline = None
    passed = _execute_assertion(execution)
    assert passed.case_outcome == "passed"
    assert passed.evidence["output"] == "credential=[REDACTED]"
    assert control.case_calls == 1


def test_dirty_ssh_path_fails_baseline_and_blocks_dependent_case() -> None:
    control = FakeHostControl(refuse_ssh_state=True)
    execution = _execution(control)

    baseline = execution.reach_baseline("shell-preconfigured")
    baseline_case_calls = control.case_calls
    blocked = _execute_assertion(execution)

    assert not baseline.ok
    assert baseline.error_code == "baseline_verification_failed"
    assert baseline.evidence["observed_present"] == {
        "login": True,
        "ssh": False,
    }
    assert blocked.case_outcome == "blocked_on_precondition"
    assert blocked.evidence["case_started"] is False
    assert control.case_calls == baseline_case_calls
