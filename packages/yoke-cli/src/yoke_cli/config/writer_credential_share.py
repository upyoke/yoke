"""Move same-server connections onto the credential that replaced theirs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config.machine_config_mutation import (
    MachineConfigWriteError,
    load_payload,
    serialized_mutation,
    write_payload,
)
from yoke_cli.config.writer_connection_remove import (
    _connection_secret,
    _owned_connection_secret,
    _require_owner_only,
    _retirement_tombstone,
    _shared_secret_aliases,
)
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config.schema_transport import TRANSPORT_HTTPS


def same_server_credentials(
    env: str, *, path: str | Path | None = None
) -> dict[str, dict[str, str]]:
    """Return other connections to ``env``'s ``api_url`` on a different token file."""
    payload, _cfg_path = load_payload(path)
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    entry = _require_entry(connections, env)
    current = _connection_secret(entry)
    found: dict[str, dict[str, str]] = {}
    for name, other in connections.items():
        if str(name) == env or not _same_server(other, entry):
            continue
        source = other.get("credential_source")
        if (
            isinstance(source, Mapping)
            and source.get("kind") == contract.CREDENTIAL_KIND_TOKEN_FILE
            and _connection_secret(other) != current
        ):
            found[str(name)] = {str(key): str(value) for key, value in source.items()}
    return found


@serialized_mutation
def share_credential(
    env: str,
    revoked: Mapping[str, Mapping[str, str]],
    *,
    path: str | Path | None = None,
) -> list[str]:
    """Repoint ``revoked`` connections at ``env``'s credential in one write.

    ``revoked`` maps each connection to the credential source the server
    rejected. A connection whose source has changed since is left alone. A
    replaced Yoke-owned file is deleted once nothing references it; a file
    outside Yoke-owned secrets stays with its operator.
    """
    payload, cfg_path = load_payload(path)
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    entry = _require_entry(connections, env)
    source = entry.get("credential_source")
    if not isinstance(source, Mapping):
        raise MachineConfigWriteError(
            f"connection {env!r} has no credential to share; rerun `yoke connect`"
        )
    changed: list[str] = []
    replaced: dict[Path, str] = {}
    for name in sorted(revoked):
        other = connections.get(name)
        if (
            name == env
            or not _same_server(other, entry)
            or other.get("credential_source") != dict(revoked[name])
        ):
            continue
        secret = _owned_connection_secret(other)
        if secret is not None:
            replaced.setdefault(secret, name)
        other["credential_source"] = dict(source)
        changed.append(name)
    if not changed:
        return []
    staged: dict[Path, Path] = {}
    try:
        for secret, name in replaced.items():
            if _shared_secret_aliases(connections, env="", secret=secret):
                continue
            if not secret.exists():
                continue
            _require_owner_only(secret, env=name)
            tombstone = _retirement_tombstone(name)
            if tombstone.exists():
                raise MachineConfigWriteError(
                    f"credential retirement for {name!r} is ambiguous: {tombstone} "
                    "already exists; finish it with `yoke connection remove`, "
                    "or move that file away, then rerun `yoke connect`"
                )
            os.replace(secret, tombstone)
            staged[secret] = tombstone
        write_payload(payload, cfg_path)
    except BaseException:
        for secret, tombstone in reversed(tuple(staged.items())):
            os.replace(tombstone, secret)
        raise
    for tombstone in staged.values():
        tombstone.unlink()
    return changed


def _require_entry(connections: Mapping[str, Any], env: str) -> Mapping[str, Any]:
    entry = connections.get(env)
    if not isinstance(entry, dict):
        raise MachineConfigWriteError(
            f"env {env!r} has no entry in connections "
            f"(configured: {sorted(connections)}); rerun `yoke connect`"
        )
    return entry


def _same_server(other: Any, entry: Mapping[str, Any]) -> bool:
    return (
        isinstance(other, dict)
        and other.get("transport") == TRANSPORT_HTTPS
        and entry.get("transport") == TRANSPORT_HTTPS
        and bool(entry.get("api_url"))
        and other.get("api_url") == entry.get("api_url")
    )


__all__ = ["same_server_credentials", "share_credential"]
