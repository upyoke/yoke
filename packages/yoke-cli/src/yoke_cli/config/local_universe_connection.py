"""Record the owned local connection and repair stale machine references."""

from pathlib import Path
from typing import Any, Dict, Optional

from yoke_cli.config import machine_config, writer
from yoke_cli.config import secrets as machine_secrets
from yoke_contracts.machine_config import schema as contract

LOCAL_ENV = "local"


class LocalUniverseSetupError(RuntimeError):
    """The local universe could not be initialized, exported, or recorded."""


def ensure_local_connection(
    dsn: str,
    *,
    force: bool,
    config_path: Optional[str],
    equivalent_dsns: tuple[str, ...] = (),
    actor_universe_mismatch: bool = False,
) -> Dict[str, Any]:
    """Record the local DSN under ``connections.local`` without clobbering."""
    payload = machine_config.load_config(config_path)
    connections = payload.get("connections")
    entry = connections.get(LOCAL_ENV) if isinstance(connections, dict) else None
    if isinstance(entry, dict):
        transport = str(entry.get("transport") or "").strip()
        existing_dsn = stored_dsn(entry)
        if (
            transport == contract.DEFAULT_TRANSPORT
            and not contract.connection_is_protected(entry)
            and existing_dsn == dsn
        ):
            return {"env": LOCAL_ENV, "connection": dict(entry), "written": False}
        same_cluster_relocation = (
            transport == contract.DEFAULT_TRANSPORT
            and not contract.connection_is_protected(entry)
            and existing_dsn in equivalent_dsns
        )
        source = entry.get("credential_source") or {}
        missing_secret = (
            source.get("kind") == contract.CREDENTIAL_KIND_DSN_FILE
            and bool(source.get("path"))
            and not Path(source["path"]).expanduser().exists()
        )
        repairable = (
            transport == contract.DEFAULT_TRANSPORT
            and not contract.connection_is_protected(entry)
            and (missing_secret or actor_universe_mismatch)
        )
        if not force and not same_cluster_relocation and not repairable:
            raise LocalUniverseSetupError(
                f"local_connection_conflict: machine config has a {LOCAL_ENV!r} connection that "
                f"does not match the local universe (transport "
                f"{transport or 'unset'!s}); run `yoke init --local --force` to replace it"
            )
    try:
        # replace=True: a conflicting entry being overwritten under --force
        # must not leak stray keys (e.g. an https entry's api_url) into the
        # rewritten local connection.
        result = writer.set_connection(
            LOCAL_ENV,
            transport=contract.DEFAULT_TRANSPORT,
            dsn=dsn,
            protected=False,
            replace=True,
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise LocalUniverseSetupError(str(exc)) from exc
    result["repairs"] = []
    if isinstance(entry, dict) and repairable:
        if missing_secret:
            result["repairs"].append("missing credential file")
        if actor_universe_mismatch:
            result["repairs"].append("operating actor belongs to another universe")
    result["written"] = True
    return result


def stored_dsn(entry: Dict[str, Any]) -> Optional[str]:
    source = entry.get("credential_source")
    if not isinstance(source, dict):
        return None
    if source.get("kind") != contract.CREDENTIAL_KIND_DSN_FILE:
        return None
    dsn_path = source.get("path")
    if not dsn_path:
        return None
    try:
        return machine_secrets.read_secret_file(dsn_path, "DSN")
    except machine_secrets.MachineSecretError:
        return None
