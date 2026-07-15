"""Owner-only machine connection retirement."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_machine_operation, machine_config
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config.machine_config_mutation import (
    MachineConfigWriteError,
    load_payload,
    serialized_mutation,
    write_payload,
)
from yoke_contracts.machine_config import schema as contract


@github_machine_operation.serialized_operation(MachineConfigWriteError)
@serialized_mutation
def remove_connection(
    env: str, *, path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove an inactive alias and its Yoke-owned credential atomically."""
    payload, cfg_path = load_payload(path)
    if not cfg_path.is_file():
        raise MachineConfigWriteError(f"machine config is missing: {cfg_path}")
    stat = cfg_path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise MachineConfigWriteError(
            "machine config retirement requires an owner-only config file"
        )
    if str(payload.get("active_env") or "") == env:
        raise MachineConfigWriteError(
            f"refusing to remove active authority {env!r}; select the canonical "
            "replacement with `yoke env use` first"
        )
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    entry = connections.get(env)
    retirement = _retirement_tombstone(env)
    if not isinstance(entry, dict):
        tombstone = _existing_recovery_tombstone(env, retirement)
        entries = contract.normalize_projects(payload.get("projects"))
        payload["projects"] = [entry for entry in entries if entry.get("env") != env]
        if len(entries) != len(payload["projects"]):
            write_payload(payload, cfg_path)
        if tombstone is not None:
            _require_owner_only(tombstone, env=env)
            tombstone.unlink()
        return {
            "removed_env": env, "already_removed": True,
            "credential_removed": tombstone is not None,
            "credential_retained_shared": False,
            "project_mappings_removed": len(entries) - len(payload["projects"]),
            "config": str(cfg_path),
        }

    secret = _owned_connection_secret(entry)
    shared = _shared_secret_aliases(connections, env=env, secret=secret)
    tombstone = None
    if secret is not None:
        legacy = secret.with_name(secret.name + ".retiring")
        existing = retirement if retirement.exists() else (
            legacy if legacy.exists() else None
        )
        if existing is not None and secret.exists():
            raise MachineConfigWriteError(
                f"credential retirement for {env!r} is ambiguous"
            )
        if shared:
            if existing is not None:
                _require_owner_only(existing, env=env)
                os.replace(existing, secret)
        elif secret.exists():
            _require_owner_only(secret, env=env)
            os.replace(secret, retirement)
            tombstone = retirement
        elif existing is not None:
            _require_owner_only(existing, env=env)
            tombstone = existing
    connections.pop(env)
    entries = contract.normalize_projects(payload.get("projects"))
    payload["projects"] = [entry for entry in entries if entry.get("env") != env]
    try:
        write_payload(payload, cfg_path)
    except BaseException:
        if tombstone is not None:
            os.replace(tombstone, secret)
        raise
    if tombstone is not None:
        tombstone.unlink()
    return {
        "removed_env": env,
        "credential_removed": tombstone is not None,
        "credential_retained_shared": bool(shared),
        "project_mappings_removed": len(entries) - len(payload["projects"]),
        "config": str(cfg_path),
    }


def _owned_connection_secret(entry: Mapping[str, Any]) -> Path | None:
    source = entry.get("credential_source")
    if not isinstance(source, Mapping):
        return None
    raw = str(source.get("path") or "").strip()
    if not raw:
        return None
    selected = Path(raw).expanduser().resolve()
    expected = (machine_config.yoke_home() / contract.SECRETS_DIR_NAME).resolve()
    if selected.parent != expected:
        raise MachineConfigWriteError(
            "refusing to remove a credential outside Yoke-owned machine secrets"
        )
    return selected


def _shared_secret_aliases(
    connections: Mapping[str, Any], *, env: str, secret: Path | None,
) -> list[str]:
    if secret is None:
        return []
    aliases = []
    for alias, other in connections.items():
        if alias == env or not isinstance(other, Mapping):
            continue
        if _owned_connection_secret(other) == secret:
            aliases.append(str(alias))
    return sorted(aliases)


def _retirement_tombstone(env: str) -> Path:
    digest = hashlib.sha256(env.encode("utf-8")).hexdigest()[:20]
    return (
        machine_config.yoke_home() / contract.SECRETS_DIR_NAME
        / f".connection-{digest}.retiring"
    )


def _existing_recovery_tombstone(env: str, retirement: Path) -> Path | None:
    if retirement.exists():
        return retirement
    candidates = [
        machine_secrets.secret_path_no_create(env, suffix).with_name(
            machine_secrets.secret_path_no_create(env, suffix).name + ".retiring"
        )
        for suffix in ("token", "dsn")
    ]
    existing = [candidate for candidate in candidates if candidate.exists()]
    if len(existing) > 1:
        raise MachineConfigWriteError(
            f"multiple interrupted credential retirements found for {env!r}"
        )
    return existing[0] if existing else None


def _require_owner_only(path: Path, *, env: str) -> None:
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise MachineConfigWriteError(
            f"refusing to remove non-owner credential for {env!r}"
        )


__all__ = ["remove_connection"]
