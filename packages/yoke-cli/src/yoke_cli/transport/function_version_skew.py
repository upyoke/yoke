"""Typed version-skew gate for relayed function calls.

A relayed function id the active env does not serve is a client/server
registry-skew fact, not an unknown function. The server answers
``function_not_registered`` because its registry is the older — or the
newer — one, and that raw code leaves the caller guessing between a
typo, a permissions wall, and being ahead of the deployed engine. This
module converts the answer into the typed ``function_version_skew``
error naming the function, both engine versions, and the recovery that
matches the direction of the skew.

Both directions are covered. A client ahead of the env waits for the
deploy that carries its engine; a client behind the env — one whose
function id the server has since removed or renamed — updates itself.
When neither version resolves, the error names both recoveries rather
than guessing.

In-process dispatch is immune by construction: one process holds one
registry, so this gate applies only to the HTTPS relay.
"""

from __future__ import annotations

from functools import lru_cache

from yoke_contracts.api.function_call import FunctionError
from yoke_contracts.engine_version import compare_engine_versions

#: Error code replacing a relayed ``function_not_registered``.
SKEW_ERROR_CODE = "function_version_skew"

#: Rendered in place of an engine version that does not resolve — a
#: source-run process or a server that advertises no handshake value.
UNKNOWN_VERSION = "unknown"

_SERVER_BEHIND_RECOVERY = (
    "The deployed server predates this client build. Retry after the env "
    "deploys an engine carrying that function, or use the older command "
    "form this env still serves."
)
_CLIENT_BEHIND_RECOVERY = (
    "This client build predates the deployed server, which no longer "
    "serves that function. For a self-host bundle, run `yoke self-host "
    "upgrade --dir <bundle>` to advance the CLI and pinned server image "
    "together, then retry. For another environment, install the CLI release "
    "that environment advertises."
)
_UNDETERMINED_RECOVERY = (
    "The engine versions do not establish which side is behind: either "
    "the env has not yet deployed an engine carrying that function (retry "
    "after deploy), or this client build predates the deployed server and "
    "no longer matches its registry (for a self-host bundle, run `yoke "
    "self-host upgrade --dir <bundle>`; otherwise install the CLI release "
    "that environment advertises)."
)


@lru_cache(maxsize=1)
def local_function_ids() -> frozenset:
    """Function ids this CLI build can dispatch, from its own registries.

    The CLI adapter table is not the whole dispatch surface. Internal
    functions have no subcommand and still go through HTTPS
    ``/v1/functions/call``; the handler registry is the same table the
    serving API loads at lifespan. An internal id this build registers
    is a version-skew fact when the relay answers
    ``function_not_registered``.

    Lazily imported so the transport layer stays importable on a machine
    whose registries fail to load; an empty set simply disables the
    gate, which then leaves the server's original error alone.
    """
    ids: set[str] = set()
    try:
        from yoke_cli.commands.registry import (
            SUBCOMMAND_ALIAS_REGISTRY,
            SUBCOMMAND_REGISTRY,
        )
    except Exception:
        pass
    else:
        ids.update(function_id for function_id, _adapter in SUBCOMMAND_REGISTRY.values())
        ids.update(
            function_id for function_id, _adapter in SUBCOMMAND_ALIAS_REGISTRY.values()
        )
    try:
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
        from yoke_core.domain.yoke_function_registry import list_entries

        register_all_handlers()
        ids.update(entry.function_id for entry in list_entries())
    except Exception:
        pass
    return frozenset(ids)


def skew_error(
    *,
    function_id: str,
    client_version: str,
    server_version: str,
    env_name: str = "",
    extra_hint: str = "",
) -> FunctionError:
    """Build the typed skew error for an unserved *function_id*."""
    client = client_version or UNKNOWN_VERSION
    server = server_version or UNKNOWN_VERSION
    env = f"env {env_name!r}" if env_name else "env"
    message = (
        f"the active HTTPS {env} does not serve function {function_id!r}: "
        f"client engine version {client}, server engine version {server} — "
        "the client and server function registries have skewed"
    )
    recovery = _recovery_for_direction(client_version, server_version)
    if extra_hint:
        recovery = f"{recovery}\n\n{extra_hint}"
    return FunctionError(
        code=SKEW_ERROR_CODE,
        message=message,
        recovery_hint=recovery,
    )


def _recovery_for_direction(client_version: str, server_version: str) -> str:
    comparison = compare_engine_versions(client_version, server_version)
    if comparison is None or comparison == 0:
        return _UNDETERMINED_RECOVERY
    return _SERVER_BEHIND_RECOVERY if comparison > 0 else _CLIENT_BEHIND_RECOVERY


__all__ = [
    "SKEW_ERROR_CODE",
    "UNKNOWN_VERSION",
    "local_function_ids",
    "skew_error",
]
