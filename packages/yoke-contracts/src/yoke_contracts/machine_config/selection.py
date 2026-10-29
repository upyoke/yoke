"""Machine-local connection selection and scoped CLI project references."""

from contextvars import ContextVar
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config.schema_connections import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
    MachineConfigContractError,
    configured_active_env,
)

PROJECT_CONNECTION: ContextVar[str] = ContextVar("project_connection", default="")
SELECTION_REASON: ContextVar[str] = ContextVar(
    "connection_selection_reason", default=""
)


def connection_groups(payload: Mapping[str, Any]) -> dict[str, list[dict]]:
    """Combine admin registrations with their ordinary connection namespace."""
    from yoke_contracts.machine_config.schema_projects import (
        connection_project_maps,
        normalize_projects,
    )

    connections = payload.get("connections") or {}
    result: dict[str, list[dict]] = {}
    for label, entries in connection_project_maps(payload).items():
        env = str(label)
        if env.endswith(DB_ADMIN_ENV_SUFFIX):
            base = env[: -len(DB_ADMIN_ENV_SUFFIX)]
            if base in connections:
                env = base
            else:
                continue  # Admin doors are selected only by explicit override.
        if env not in connections:
            continue  # Retired connections retain registrations, not routing authority.
        result.setdefault(env, []).extend(normalize_projects(entries))
    return result


def checkout_connection(
    payload: Mapping[str, Any], cwd: str | Path | None = None
) -> str:
    """Select the deepest registered checkout containing cwd or its Git primary."""
    from yoke_contracts.machine_config.checkout import main_checkout

    current = Path(cwd or os.getcwd()).resolve()
    groups = connection_groups(payload)
    if not groups:
        return ""
    primary = main_checkout(current)
    matches: list[tuple[int, str]] = []
    for env, entries in groups.items():
        for entry in entries:
            root = Path(entry["checkout"]).expanduser().resolve()
            if current.is_relative_to(root) or primary == root:
                matches.append((len(root.parts), env))
    if not matches:
        return ""
    depth = max(size for size, _ in matches)
    candidates = {env for size, env in matches if size == depth}
    if len(candidates) > 1:
        raise MachineConfigContractError(
            "checkout_connection_ambiguous: checkout matches connections "
            f"{', '.join(sorted(candidates))}; pass --env ENV, or run "
            "`yoke --env ENV project register CHECKOUT --project-id N --reassign` "
            "to move the duplicate registration"
        )
    return candidates.pop()


def connection_selection(
    payload: Mapping[str, Any], explicit_env: str | None = None
) -> tuple[str, str]:
    """Return the connection label and the authority that selected it."""
    if explicit_env and explicit_env.strip():
        return explicit_env.strip(), "explicit_flag"
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return override, SELECTION_REASON.get() or "env_var"
    checkout = checkout_connection(payload)
    if checkout:
        return checkout, "checkout"
    if PROJECT_CONNECTION.get():
        return PROJECT_CONNECTION.get(), "project_reference"
    fallback = configured_active_env(payload)
    if not fallback:
        raise MachineConfigContractError(
            "active env is not configured; run `yoke env use <env>` or pass --env"
        )
    return fallback, "active_env"
