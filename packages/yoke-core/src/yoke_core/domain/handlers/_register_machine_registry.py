"""Register the machine-registry function family."""

from __future__ import annotations

from yoke_core.domain.handlers import machine_registry as _machines
from yoke_core.domain.handlers import machine_lifecycle as _lifecycle


_READS = (
    (
        "machine.list",
        _machines.handle_machine_list,
        _machines.MachineListRequest,
        _machines.MachineListResponse,
    ),
    (
        "machine.show",
        _machines.handle_machine_show,
        _machines.MachineShowRequest,
        _machines.MachineRecordResponse,
    ),
    (
        "machine.detail",
        _lifecycle.handle_machine_detail,
        _machines.MachineShowRequest,
        _lifecycle.MachineDetailResponse,
    ),
    (
        "machine.settings.get",
        _machines.handle_machine_settings_get,
        _machines.MachineSettingsGetRequest,
        _machines.MachineSettingsGetResponse,
    ),
)


def _register(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
    *,
    side_effects,
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module=_machines.__name__,
        target_kinds=["global"],
        side_effects=side_effects,
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["verified_actor", "handler_enforced_machine_ownership"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


def register(registry) -> None:
    for function_id, handler, request_model, response_model in _READS:
        _register(
            registry,
            function_id,
            handler,
            request_model,
            response_model,
            side_effects=[],
        )
    _register(
        registry,
        "machine.register",
        _lifecycle.handle_machine_register,
        _lifecycle.MachineRegisterRequest,
        _lifecycle.MachineRegisterResponse,
        side_effects=["machines_upsert", "machine_credential_rotate"],
    )
    _register(
        registry,
        "machine.retire",
        _lifecycle.handle_machine_retire,
        _lifecycle.MachineRetireRequest,
        _machines.MachineRecordResponse,
        side_effects=["machines_update", "machine_credential_revoke"],
    )
    _register(
        registry,
        "machine.settings.set",
        _machines.handle_machine_settings_set,
        _machines.MachineSettingsSetRequest,
        _machines.MachineRecordResponse,
        side_effects=["machines_update"],
    )


__all__ = ["register"]
