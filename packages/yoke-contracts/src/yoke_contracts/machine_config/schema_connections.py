"""Connection-level helpers for the machine-config contract."""

from __future__ import annotations

import os
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_transport import (
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
)

ENV_OVERRIDE = "YOKE_ENV"
PROD_FLAG_KEY = "prod"
#: Label suffix pairing a direct-Postgres admin connection with the https
#: connection serving the same universe (``prod`` <-> ``prod-db-admin``).
DB_ADMIN_ENV_SUFFIX = "-db-admin"


class MachineConfigContractError(RuntimeError):
    """Raised when the selected machine config cannot be used."""


def selected_env(payload: Mapping[str, Any], explicit_env: str | None = None) -> str:
    """Resolve env precedence: explicit, ``YOKE_ENV``, then ``active_env``."""
    requested = (explicit_env or "").strip() or os.environ.get(ENV_OVERRIDE, "").strip()
    configured = str(payload.get("active_env") or "").strip()
    selected = requested or configured
    if not selected:
        raise MachineConfigContractError(
            "active env is not configured; run `yoke env use <env>` or pass --env"
        )
    return selected


def connection_is_prod(connection: Mapping[str, Any]) -> bool:
    """Return the explicit prod marker without inferring from names or DSNs."""
    return connection.get(PROD_FLAG_KEY) is True


def local_postgres_envs(
    payload: Mapping[str, Any] | None,
    *,
    include_prod: bool = False,
) -> list[str]:
    """Env labels whose connection declares local-postgres.

    Recipe *selection* still defaults to non-prod local Postgres entries.
    Refusal inventory that must agree with ``yoke env list`` passes
    ``include_prod=True`` so a prod-flagged admin sibling the recipe just
    named is not omitted from the list.
    """
    if not isinstance(payload, Mapping):
        return []
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return []
    return sorted(
        str(env)
        for env, entry in connections.items()
        if isinstance(entry, Mapping)
        and str(entry.get("transport") or "").strip() in POSTGRES_TRANSPORTS
        and (include_prod or not connection_is_prod(entry))
    )


def _connection(payload: Mapping[str, Any] | None, env: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or not env:
        return {}
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return {}
    entry = connections.get(env)
    return entry if isinstance(entry, Mapping) else {}


def _transport(payload: Mapping[str, Any] | None, env: str) -> str:
    return str(_connection(payload, env).get("transport") or "").strip()


def same_universe_db_admin_env(payload: Mapping[str, Any] | None, env: str) -> str:
    """The direct-Postgres env administering the same universe as *env*.

    A machine whose control plane is https reaches its rows through the
    server; an operation that genuinely needs a database on this machine
    has exactly one correct target, and it is not "whichever local-postgres
    connection happens to sort first". The connections that answer for the
    same universe are paired by label — ``prod`` is administered by
    ``prod-db-admin`` — so a recovery recipe naming any other local env
    sends the operator to a database that does not contain their work.

    Returns ``""`` when no such sibling is configured, including for an env
    that is already the admin side of a pair.
    """
    env = str(env or "").strip()
    if not env or env.endswith(DB_ADMIN_ENV_SUFFIX):
        return ""
    sibling = f"{env}{DB_ADMIN_ENV_SUFFIX}"
    if _transport(payload, sibling) in POSTGRES_TRANSPORTS:
        return sibling
    return ""


def same_universe_https_env(payload: Mapping[str, Any] | None, env: str) -> str:
    """The https env whose universe *env* administers directly.

    The inverse pairing of :func:`same_universe_db_admin_env`. A client
    holding an owner-only database connection still has to reach
    server-held authority — GitHub App credentials, for one — through an
    https plane, and the plane that owns those credentials for its rows is
    the one this connection administers, not an independently deployed
    peer. Returns ``""`` when *env* is not an admin label or its https
    counterpart is not configured.
    """
    env = str(env or "").strip()
    if not env.endswith(DB_ADMIN_ENV_SUFFIX):
        return ""
    base = env[: -len(DB_ADMIN_ENV_SUFFIX)]
    return base if _transport(payload, base) == TRANSPORT_HTTPS else ""


def env_override_teaching(
    payload: Mapping[str, Any] | None,
    *,
    selected_env: str,
    transport: str,
    command: str | None = None,
) -> str:
    """Setup-error text for a local-postgres-only operation under a non-local
    selected env: why it failed, the configured local-postgres envs, and the
    one-line override recipe.

    Recipe *selection* still prefers the selected env's admin sibling, then a
    non-prod local-postgres fallback — never a random prod database. The
    parenthetical inventory is the full local-postgres set ``yoke env list``
    would show, including prod-flagged admin connections the recipe just named.
    """
    retry_envs = local_postgres_envs(payload)
    inventory_envs = local_postgres_envs(payload, include_prod=True)
    # The sibling that administers the SELECTED env's own universe outranks
    # the configured inventory: a recipe naming another machine-local
    # database sends the operator somewhere their rows do not exist.
    sibling = same_universe_db_admin_env(payload, selected_env)
    why = (
        f"connected env {selected_env!r} (transport {transport}) has no local "
        "Postgres; this operation requires a local-postgres env."
    )
    if not sibling and not retry_envs:
        return (
            f"{why} No local-postgres env is configured on this machine; add "
            "one under connections in ~/.yoke/config.json "
            "(see `yoke config example`)."
        )
    recipe_env = sibling or retry_envs[0]
    recipe_cmd = command if command is not None else _invocation_recipe()
    universe = (
        f" {recipe_env!r} administers the same universe as {selected_env!r}."
        if sibling
        else ""
    )
    inventory = (
        f"configured local-postgres envs: {', '.join(inventory_envs)}; "
        if inventory_envs
        else ""
    )
    return (
        f"{why}{universe} Run: {ENV_OVERRIDE}={recipe_env} {recipe_cmd} "
        f"({inventory}`yoke` subcommands also accept --env {recipe_env})."
    )


def _argv_without_env_override(args: list[str]) -> list[str]:
    """Drop ``--env NAME`` / ``--env=NAME`` from a reconstructed recipe.

    Recovery teaching already supplies the env via ``YOKE_ENV=``. Echoing
    the caller's ``--env`` recreates the failed selection on ``yoke``
    (explicit ``--env`` outranks ``YOKE_ENV``) and is not a flag
    ``python -m yoke_core.cli.db_router`` accepts — the first positional
    is a domain, so ``--env`` becomes ``unknown domain``.
    """
    out: list[str] = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        if arg == "--env":
            skip_value = True
            continue
        if arg.startswith("--env="):
            continue
        out.append(arg)
    return out


def _invocation_recipe(
    argv: list[str] | None = None,
    main_spec_name: str | None = None,
    interpreter: str | None = None,
) -> str:
    """Reconstruct the current invocation for the override recipe line.

    The recipe is the accepted command shape, not a replay of caller
    argv: ``--env`` is stripped because this teaching already prepends
    ``YOKE_ENV=``. A module-form recipe names the interpreter that is
    running right now rather than a bare ``python3``: the failing process
    reached its imports through this interpreter, and the ambient one on
    ``PATH`` frequently cannot import the packages the recipe would re-enter.
    """
    import shlex
    import sys
    from pathlib import Path

    args = list(sys.argv) if argv is None else list(argv)
    if main_spec_name is None:
        spec = getattr(sys.modules.get("__main__"), "__spec__", None)
        main_spec_name = getattr(spec, "name", "") or ""
    module = main_spec_name.removesuffix(".__main__")
    if module and module != "__main__":
        python = interpreter or sys.executable or "python3"
        prefix = f"{shlex.quote(python)} -m {module}"
    else:
        prefix = Path(args[0]).name if args and args[0] else "<command>"
    tail = " ".join(shlex.quote(arg) for arg in _argv_without_env_override(args[1:]))
    return f"{prefix} {tail}".strip()


__all__ = [
    "DB_ADMIN_ENV_SUFFIX",
    "ENV_OVERRIDE",
    "MachineConfigContractError",
    "PROD_FLAG_KEY",
    "connection_is_prod",
    "env_override_teaching",
    "local_postgres_envs",
    "same_universe_db_admin_env",
    "same_universe_https_env",
    "selected_env",
]
