"""Import the retired flat map once during an explicit config write."""

from yoke_contracts.machine_config.schema_connections import configured_active_env
from yoke_contracts.machine_config.schema_projects import normalize_projects


def import_project_connections(payload: dict) -> None:
    """Preserve the old reader's snapshot; new readers never fall back to it."""
    if "connection_projects" in payload:
        return
    entries = normalize_projects(payload.get("projects"))
    if not entries:
        payload["connection_projects"] = {}
        return
    default = configured_active_env(payload)
    if not default:
        from yoke_contracts.machine_config.schema_connections import (
            MachineConfigContractError,
        )

        raise MachineConfigContractError(
            "project_connection_upgrade_required: set active_env to the connection "
            "owning the legacy project ids, then rerun project register"
        )
    # Configured default is deliberate: an --env override cannot relabel old ids.
    from yoke_contracts.machine_config.schema_connections import same_universe_https_env

    connection = same_universe_https_env(payload, default) or default
    payload["connection_projects"] = {connection: [dict(entry) for entry in entries]}
