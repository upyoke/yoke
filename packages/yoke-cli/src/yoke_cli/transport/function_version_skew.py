"""Typed version-skew gate for relayed function calls.

A relayed function id the active env does not serve is a client/server
registry-skew fact, not an unknown function. The server answers
``function_not_registered`` because its registry is the older — or the
newer — one, and that raw code leaves the caller guessing between a
typo, a permissions wall, and being ahead of the deployed engine. This
module converts the answer into the typed ``function_version_skew``
error naming the function, both engine versions, and the recovery that
matches the direction of the skew.

Both directions are covered. A client ahead of the env uses the older
command this env still serves, or escalates the missing command to the
control-plane operator; it does not wait on a deploy
that itself needs the missing function. A client behind the env — one
whose function id the server has since removed or renamed — updates
itself. When a function declares ``minimum_serving_version``, the
refusal names that floor. When neither version resolves, the error
names both recoveries rather than guessing.

In-process dispatch is immune by construction: one process holds one
registry, so this gate applies only to the HTTPS relay.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, Mapping

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    FunctionError,
)
from yoke_contracts.engine_version import (
    compare_engine_versions,
    local_handshake_version,
)
from yoke_contracts.function_serving_floors import (
    FUNCTION_MINIMUM_SERVING_VERSIONS,
    ArgumentFloor,
    declared_argument_floors,
    declared_minimum_serving_version,
)

#: Error code replacing a relayed ``function_not_registered``.
SKEW_ERROR_CODE = "function_version_skew"
#: Error code replacing a relayed ``payload_invalid`` for a floored argument.
ARGUMENT_SKEW_ERROR_CODE = "function_argument_version_skew"

#: Rendered in place of an engine version that does not resolve — a
#: source-run process or a server that advertises no handshake value.
UNKNOWN_VERSION = "unknown"

_SERVER_BEHIND_RECOVERY = (
    "The deployed server predates this client build. Use the older command "
    "form this env still serves. If none covers the required operation, "
    "escalate the missing command to the control-plane operator, naming "
    "the function and versions above. This also applies when the missing "
    "function is on the deploy path."
)
_CLIENT_BEHIND_RECOVERY = (
    "This client build predates the deployed server, which no longer "
    "serves that function. For a self-host bundle, run `yoke self-host "
    "upgrade --dir <bundle>` to advance the CLI and pinned server image "
    "together, then retry. For another environment, install the CLI release "
    "that environment advertises."
)
_UNDETERMINED_RECOVERY = (
    "The engine versions do not establish which side is behind. If this "
    "client build predates the deployed server, for a self-host bundle "
    "run `yoke self-host upgrade --dir <bundle>`; otherwise install the "
    "CLI release that environment advertises. If the server predates this "
    "client, use the older command form this env still serves. If none "
    "covers the required operation, escalate the missing command to the "
    "control-plane operator, naming the function and versions above."
)


@lru_cache(maxsize=1)
def local_function_ids() -> frozenset:
    """Function ids this CLI build can dispatch, from its own registries
    and the new ids it declares serving floors for.

    Lazily imported so the transport layer stays importable on a machine
    whose command registries fail to load; an empty set simply disables
    the gate, which then leaves the server's original error alone.
    """
    try:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_ALIAS_REGISTRY,
            SUBCOMMAND_REGISTRY,
        )
    except Exception:
        return frozenset()
    ids = {function_id for function_id, _adapter in SUBCOMMAND_REGISTRY.values()}
    ids.update(
        function_id for function_id, _adapter in SUBCOMMAND_ALIAS_REGISTRY.values()
    )
    # A function this build declares a serving floor for is one it calls,
    # including those a command reaches internally rather than by name.
    ids.update(FUNCTION_MINIMUM_SERVING_VERSIONS)
    return frozenset(ids)


def skew_error(
    *,
    function_id: str,
    client_version: str,
    server_version: str,
    env_name: str = "",
    extra_hint: str = "",
    minimum_serving_version: str = "",
) -> FunctionError:
    """Build the typed skew error for an unserved *function_id*."""
    client = client_version or UNKNOWN_VERSION
    server = server_version or UNKNOWN_VERSION
    env = f"env {env_name!r}" if env_name else "env"
    floor = (
        minimum_serving_version or declared_minimum_serving_version(function_id)
    ).strip()
    floor_clause = f" (minimum serving version {floor})" if floor else ""
    message = (
        f"the active HTTPS {env} does not serve function {function_id!r}"
        f"{floor_clause}: client engine version {client}, "
        f"server engine version {server} — the client and server function "
        "registries have skewed"
    )
    recovery = _recovery_for_direction(client_version, server_version)
    if extra_hint:
        recovery = f"{recovery}\n\n{extra_hint}"
    return FunctionError(
        code=SKEW_ERROR_CODE,
        message=message,
        recovery_hint=recovery,
    )


def argument_skew_error(
    *,
    function_id: str,
    floors: Mapping[str, ArgumentFloor],
    client_version: str,
    server_version: str,
    env_name: str = "",
    server_message: str = "",
) -> FunctionError:
    """Name the floor when an older server rejects a newly added argument."""
    env = f"env {env_name!r}" if env_name else "env"
    named = ", ".join(
        f"{name} (minimum serving version {floor.minimum_serving_version})"
        for name, floor in sorted(floors.items())
    )
    older = "; ".join(sorted({floor.older_form for floor in floors.values()}))
    message = (
        f"the active HTTPS {env} does not accept argument {named} of function "
        f"{function_id!r}: client engine version {client_version or UNKNOWN_VERSION}, "
        f"server engine version {server_version or UNKNOWN_VERSION}"
    )
    if server_message:
        message = f"{message}; the server answered: {server_message[:300]}"
    return FunctionError(
        code=ARGUMENT_SKEW_ERROR_CODE,
        message=message,
        recovery_hint=(
            f"The deployed server predates that argument. Send {older} "
            "instead, which this env still accepts. If that cannot do the "
            "required operation, escalate to the control-plane operator, "
            "naming the function, argument, and versions above."
        ),
    )


def retype_skew(
    response: FunctionCallResponse,
    request: FunctionCallRequest,
    *,
    server_version: str,
    env_name: str,
    function_hint: Callable[[str], str] | None = None,
) -> FunctionCallResponse:
    """Retype a relayed answer that is really client/server registry skew.

    The server says ``function_not_registered`` about its own registry; for a
    function this build can dispatch, that answer is a version-skew fact and
    is replaced with the typed error naming both engine versions and the
    direction-matched recovery. A function id this build does not know is a
    genuine unknown function, so the server's answer stands. A
    ``payload_invalid`` for a call carrying a floored argument is the same
    fact one level down: the server's request model predates the argument.
    """
    if response.success or response.error is None:
        return response
    floors = declared_argument_floors(request.function, request.payload)
    if response.error.code == "payload_invalid" and floors:
        error = argument_skew_error(
            function_id=request.function,
            floors=floors,
            client_version=local_handshake_version(),
            server_version=server_version,
            env_name=env_name,
            server_message=response.error.message,
        )
        return response.model_copy(update={"error": error})
    if response.error.code != "function_not_registered":
        return response
    if request.function not in local_function_ids():
        return response
    extra_hint = function_hint(request.function) if function_hint else ""
    error = skew_error(
        function_id=request.function,
        client_version=local_handshake_version(),
        server_version=server_version,
        env_name=env_name,
        extra_hint=extra_hint or "",
    )
    return response.model_copy(update={"error": error})


def _recovery_for_direction(client_version: str, server_version: str) -> str:
    comparison = compare_engine_versions(client_version, server_version)
    if comparison is None or comparison == 0:
        return _UNDETERMINED_RECOVERY
    return _SERVER_BEHIND_RECOVERY if comparison > 0 else _CLIENT_BEHIND_RECOVERY


__all__ = [
    "ARGUMENT_SKEW_ERROR_CODE",
    "SKEW_ERROR_CODE",
    "argument_skew_error",
    "UNKNOWN_VERSION",
    "local_function_ids",
    "retype_skew",
    "skew_error",
]
