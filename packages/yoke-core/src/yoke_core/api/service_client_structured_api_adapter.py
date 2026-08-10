"""Core-side import facade for the Yoke CLI dispatcher transport."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_cli.transport.dispatcher import (
    build_actor,
    build_request,
    emit_response,
    response_to_dict,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.api.service_client_structured_api_adapter_inventory import (
    AGENT_PATH_VALUES,
    AdapterEntry,
    CLI_ADAPTERS,
    adapter_index,
)
from yoke_core.api.service_client_shared_session_resolver import _resolve_session_id


def dispatch(request: FunctionCallRequest) -> FunctionCallResponse:
    """Dispatch in-process against core; imported lazily for client safety."""

    from yoke_core.domain.yoke_function_dispatch import dispatch as _dispatch

    return _dispatch(request)


def call_dispatcher(
    *,
    function_id: str,
    target: TargetRef,
    payload: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None,
    preconditions: Optional[Dict[str, Any]] = None,
    actor: Optional[ActorContext] = None,
    request_id: Optional[str] = None,
    intent: Optional[str] = None,
    timeout_s: Optional[float] = None,
    local_only: bool = False,
) -> FunctionCallResponse:
    """Build a request envelope and route it via the client dispatcher."""

    from yoke_cli.transport.dispatcher import call_dispatcher as _call

    return _call(
        function_id=function_id,
        target=target,
        payload=payload,
        options=options,
        preconditions=preconditions,
        actor=actor,
        request_id=request_id,
        intent=intent,
        timeout_s=timeout_s,
        local_only=local_only,
        _local_dispatch=dispatch,
        _function_hint=_function_not_registered_hint,
    )


def _function_not_registered_hint(function_id: str) -> str:
    """The dogfooding recovery this checkout can add to a skew error.

    The transport's version-skew gate already names the function, both
    engine versions, and the deploy-or-update recovery. What only a
    source checkout can add is the concrete local-postgres rerun recipe
    for the command in hand, so this hint carries exactly that.
    """
    entry = adapter_for(function_id)
    if entry is None:
        return ""
    return _local_postgres_rerun_hint(cli_invocation=entry.cli_invocation)


def _local_postgres_rerun_hint(*, cli_invocation: str) -> str:
    try:
        from yoke_core.domain import machine_config
        from yoke_contracts.machine_config.schema import (
            local_postgres_envs,
            same_universe_db_admin_env,
        )

        config = machine_config.load_config()
        # The active env's own admin sibling first: rerunning against a
        # different local universe answers about rows the caller never
        # asked about.
        sibling = same_universe_db_admin_env(config, machine_config.active_env())
        local_envs = local_postgres_envs(config)
    except Exception:
        return ""
    if not sibling and not local_envs:
        return ""
    env = sibling or local_envs[0]
    if cli_invocation.startswith("yoke "):
        recipe = cli_invocation.replace("yoke ", f"yoke --env {env} ", 1)
    else:
        recipe = f"YOKE_ENV={env} {cli_invocation}"
    inventory = (
        f" (configured local-postgres envs: {', '.join(local_envs)})"
        if local_envs
        else ""
    )
    return (
        "For dogfooding newly merged local code against the Postgres "
        f"authority, rerun with `{recipe}`{inventory}."
    )


def adapter_for(function_id: str) -> Optional[AdapterEntry]:
    """Return the registered :class:`AdapterEntry` for *function_id*."""

    return adapter_index().get(function_id)


def function_ids_with_adapter() -> List[str]:
    return sorted(adapter_index())


__all__ = [
    "AdapterEntry",
    "AGENT_PATH_VALUES",
    "CLI_ADAPTERS",
    "adapter_for",
    "build_actor",
    "build_request",
    "call_dispatcher",
    "dispatch",
    "emit_response",
    "function_ids_with_adapter",
    "_resolve_session_id",
    "response_to_dict",
]
