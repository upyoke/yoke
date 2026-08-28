"""Function registry entries for the composite test-machine capability."""

from __future__ import annotations

from yoke_core.domain.handlers import machine_qa as _handlers
from yoke_core.domain.handlers import machine_qa_list as _list
from yoke_core.domain.handlers import machine_qa_case as _case
from yoke_core.domain.handlers import machine_qa_execution_abort as _abort
from yoke_core.domain.handlers import machine_qa_plan_case as _plan_case
from yoke_core.domain import agent_mission_recording as _agent_mission


def register(registry) -> None:
    _agent_mission.register(registry)
    registry.register(
        "test_machine.plan_case.begin",
        _plan_case.handle_plan_case_begin,
        _plan_case.TestMachinePlanCaseBeginRequest,
        _plan_case.TestMachinePlanCaseBeginResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "deployment_run"],
        side_effects=[
            "qa_plan_execution_write",
            "coordination_claim",
        ],
        emitted_event_names=["LeaseAcquired", "YokeFunctionCalled"],
        guardrails=[
            "qa_subject_authority",
            "actor_session_bound",
            "durable_plan_cursor",
            "serial_plan_lease",
            "secret_free_contract",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )
    registry.register(
        "test_machine.plan_case.submit",
        _plan_case.handle_plan_case_submit,
        _plan_case.TestMachinePlanCaseSubmitRequest,
        _plan_case.TestMachinePlanCaseSubmitResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["item", "deployment_run"],
        side_effects=[
            "qa_plan_execution_write",
            "coordination_claim_heartbeat",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=[
            "LeaseHeartbeated",
            "QARunCompleted",
            "YokeFunctionCalled",
        ],
        guardrails=[
            "qa_subject_authority",
            "actor_session_bound",
            "durable_plan_cursor",
            "immutable_case_context",
            "contract_digest",
            "secret_free_result",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
        ambient_session_required=True,
    )
    registry.register(
        "test_machine.baseline_group.abort",
        _abort.handle_baseline_group_abort,
        _abort.TestMachineCaseAbortRequest,
        _abort.TestMachineExecutionAbortResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=["coordination_claim_release"],
        emitted_event_names=["LeaseReleased", "YokeFunctionCalled"],
        guardrails=["actor_owned_lease", "contract_digest"],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.baseline_group_execute",
        _case.handle_baseline_group_execute,
        _case.TestMachineBaselineGroupExecuteRequest,
        _case.TestMachineBaselineGroupExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "credential_owning_client_required",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.case.abort",
        _abort.handle_case_abort,
        _abort.TestMachineCaseAbortRequest,
        _abort.TestMachineExecutionAbortResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=["coordination_claim_release"],
        emitted_event_names=["LeaseReleased", "YokeFunctionCalled"],
        guardrails=["actor_owned_lease", "contract_digest"],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.case_execute",
        _case.handle_case_execute,
        _case.TestMachineCaseExecuteRequest,
        _case.TestMachineCaseExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "credential_owning_client_required",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.baseline_group.begin",
        _case.handle_baseline_group_begin,
        _case.TestMachineBaselineGroupExecuteRequest,
        _case.TestMachineBaselineGroupBeginResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=["coordination_claim", "qa_run_write"],
        emitted_event_names=["LeaseAcquired", "QARunStarted", "YokeFunctionCalled"],
        guardrails=[
            "materialized_case_reread",
            "server_discovered_baseline_group",
            "serial_lease",
            "lease_waiting_state",
            "secret_free_contract",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.baseline_group.submit",
        _case.handle_baseline_group_submit,
        _case.TestMachineBaselineGroupSubmitRequest,
        _case.TestMachineBaselineGroupExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[
            "coordination_claim_release",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=["LeaseReleased", "QARunCompleted", "YokeFunctionCalled"],
        guardrails=[
            "actor_owned_lease",
            "immutable_case_context",
            "contract_digest",
            "secret_free_result",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.case.begin",
        _case.handle_case_begin,
        _case.TestMachineCaseExecuteRequest,
        _case.TestMachineCaseBeginResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=["coordination_claim", "qa_run_write"],
        emitted_event_names=["LeaseAcquired", "QARunStarted", "YokeFunctionCalled"],
        guardrails=[
            "materialized_case_reread",
            "serial_lease",
            "lease_waiting_state",
            "secret_free_contract",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.case.submit",
        _case.handle_case_submit,
        _case.TestMachineCaseSubmitRequest,
        _case.TestMachineCaseExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[
            "coordination_claim_release",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=["LeaseReleased", "QARunCompleted", "YokeFunctionCalled"],
        guardrails=[
            "actor_owned_lease",
            "immutable_case_context",
            "contract_digest",
            "secret_free_result",
        ],
        adapter_status="internal",
        claim_required_kind="qa_subject",
    )
    registry.register(
        "test_machine.list",
        _list.handle_list,
        _list.TestMachineListRequest,
        _list.TestMachineListResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["secret_values_never_returned"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "test_machine.get",
        _handlers.handle_get,
        _handlers.TestMachineGetRequest,
        _handlers.TestMachineResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["secret_values_never_returned"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "test_machine.settings_replace",
        _handlers.handle_settings_replace,
        _handlers.TestMachineSettingsReplaceRequest,
        _handlers.TestMachineSettingsReplaceResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["project_capability_write", "verification_invalidation"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["cas_settings", "secret_values_forbidden"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "test_machine.verify",
        _handlers.handle_verify,
        _handlers.TestMachineGetRequest,
        _handlers.TestMachineVerifyResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["credential_owning_client_required"],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "test_machine.verify.abort",
        _abort.handle_verify_abort,
        _abort.TestMachineVerifyAbortRequest,
        _abort.TestMachineExecutionAbortResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["coordination_claim_release"],
        emitted_event_names=["LeaseReleased", "YokeFunctionCalled"],
        guardrails=["actor_owned_lease", "contract_digest"],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "test_machine.verify.begin",
        _handlers.handle_verify_begin,
        _handlers.TestMachineVerifyBeginRequest,
        _handlers.TestMachineVerifyBeginResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["coordination_claim"],
        emitted_event_names=["LeaseAcquired", "YokeFunctionCalled"],
        guardrails=[
            "serial_lease",
            "secret_free_contract",
            "registered_baselines",
        ],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "test_machine.verify.submit",
        _handlers.handle_verify_submit,
        _handlers.TestMachineVerifySubmitRequest,
        _handlers.TestMachineVerifyResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["verification_write", "coordination_claim_release"],
        emitted_event_names=["LeaseReleased", "YokeFunctionCalled"],
        guardrails=[
            "actor_owned_lease",
            "contract_digest",
            "secret_free_result",
        ],
        adapter_status="internal",
        claim_required_kind=None,
    )


__all__ = ["register"]
