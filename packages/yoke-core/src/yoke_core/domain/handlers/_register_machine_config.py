"""Register machine-config diagnostic + writer handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import machine_config, machine_config_write


def register(registry) -> None:
    _register_writers(registry)
    registry.register(
        "config.example.run",
        machine_config.handle_config_example,
        machine_config.ConfigExampleRequest,
        machine_config.ConfigExampleResponse,
        stability="beta",
        owner_module=__name__,
        target_kinds=["system"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "status.run",
        machine_config.handle_status,
        machine_config.StatusRequest,
        machine_config.StatusResponse,
        stability="beta",
        owner_module=__name__,
        target_kinds=["system"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


def _register_writers(registry) -> None:
    writers = (
        ("env.use.run", machine_config_write.handle_env_use,
         machine_config_write.EnvUseRequest,
         machine_config_write.EnvUseResponse),
        ("connection.set.run", machine_config_write.handle_connection_set,
         machine_config_write.ConnectionSetRequest,
         machine_config_write.ConnectionSetResponse),
        ("auth.set.run", machine_config_write.handle_auth_set,
         machine_config_write.AuthSetRequest,
         machine_config_write.AuthSetResponse),
        ("project.register.run", machine_config_write.handle_project_register,
         machine_config_write.ProjectRegisterRequest,
         machine_config_write.ProjectRegisterResponse),
    )
    for function_id, handler, request_model, response_model in writers:
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="beta",
            owner_module=__name__,
            target_kinds=["system"],
            side_effects=["machine_config_file_write"],
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
        )


__all__ = ["register"]
