"""Function registry entries for the composite test-machine capability."""

from __future__ import annotations

from yoke_core.domain.handlers import test_machine as _handlers
from yoke_core.domain.handlers import test_machine_case as _case


def register(registry) -> None:
    from yoke_core.domain.ssh_mac_host_control import (
        register_ssh_mac_host_control,
    )

    register_ssh_mac_host_control()
    registry.register(
        "test_machine.baseline_group_execute",
        _case.handle_baseline_group_execute,
        _case.TestMachineBaselineGroupExecuteRequest,
        _case.TestMachineBaselineGroupExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[
            "host_control",
            "coordination_lease",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=[
            "QARunStarted",
            "QARunCompleted",
            "YokeFunctionCalled",
        ],
        guardrails=[
            "materialized_case_reread",
            "server_discovered_baseline_group",
            "serial_lease",
            "lease_waiting_state",
            "registered_baseline",
            "secret_redaction",
        ],
        adapter_status="internal",
        claim_required_kind="item",
    )
    registry.register(
        "test_machine.case_execute",
        _case.handle_case_execute,
        _case.TestMachineCaseExecuteRequest,
        _case.TestMachineCaseExecuteResponse,
        stability="stable",
        owner_module=__name__,
        target_kinds=["qa_requirement"],
        side_effects=[
            "host_control",
            "coordination_lease",
            "qa_run_write",
            "qa_artifact_write",
        ],
        emitted_event_names=[
            "QARunStarted",
            "QARunCompleted",
            "YokeFunctionCalled",
        ],
        guardrails=[
            "materialized_case_reread",
            "serial_lease",
            "lease_waiting_state",
            "registered_baseline",
            "secret_redaction",
        ],
        adapter_status="internal",
        claim_required_kind="item",
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
        side_effects=["host_control", "coordination_lease", "verification_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["serial_lease", "secret_redaction", "registered_baselines"],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
