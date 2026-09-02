"""Owner-only machine connection retirement."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from yoke_cli.config import github_machine_operation, machine_config
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config.machine_config_mutation import (
    MachineConfigWriteError,
    load_payload,
    serialized_mutation,
    write_payload,
)
from yoke_contracts.machine_config import schema as contract


def remove_connection(
    env: str,
    *,
    activate: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove one alias and its Yoke-owned credential atomically."""
    result = remove_connections((env,), activate=activate, path=path)
    return {
        "removed_env": env,
        "already_removed": env in result["already_removed_envs"],
        "credential_removed": env in result["credential_removed_envs"],
        "credential_retained_shared": (
            env in result["credential_retained_shared_envs"]
        ),
        "project_mappings_removed": result["project_mappings_removed"],
        "active_env": result["active_env"],
        "config": result["config"],
    }


@github_machine_operation.serialized_operation(MachineConfigWriteError)
@serialized_mutation
def remove_connections(
    envs: Iterable[str],
    *,
    activate: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove several aliases and their unshared credentials atomically.

    Retiring the active authority needs somewhere for authority to go.
    ``activate`` names the replacement; when the alias being removed is the
    machine's last connection there is nothing to choose and the machine is
    left unconfigured, which is the honest end state of a teardown.
    """
    selected = tuple(
        dict.fromkeys(str(env).strip() for env in envs if str(env).strip())
    )
    if not selected:
        raise MachineConfigWriteError(
            "at least one connection is required for retirement"
        )
    payload, cfg_path = load_payload(path)
    if not cfg_path.is_file():
        raise MachineConfigWriteError(f"machine config is missing: {cfg_path}")
    stat = cfg_path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise MachineConfigWriteError(
            "machine config retirement requires an owner-only config file"
        )
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    unconfigured = _resolve_active_authority(
        payload,
        envs=set(selected),
        activate=activate,
        connections=connections,
    )
    entries_by_env = {
        env: connections.get(env) if isinstance(connections.get(env), dict) else None
        for env in selected
    }
    secrets_by_env = {
        env: _owned_connection_secret(entry)
        for env, entry in entries_by_env.items()
        if entry is not None
    }
    remaining = {
        str(env): entry
        for env, entry in connections.items()
        if str(env) not in selected
    }
    staged: dict[Path, tuple[Path, str]] = {}
    restored: dict[Path, tuple[Path, str]] = {}
    credential_removed: set[str] = set()
    credential_retained: set[str] = set()
    recovery_tombstones: list[tuple[Path, str]] = []
    entries = contract.normalize_projects(payload.get("projects"))
    try:
        for env in selected:
            entry = entries_by_env[env]
            if entry is None:
                tombstone = _existing_recovery_tombstone(
                    env, _retirement_tombstone(env)
                )
                if tombstone is not None:
                    _require_owner_only(tombstone, env=env)
                    recovery_tombstones.append((tombstone, env))
                    credential_removed.add(env)
                continue
            secret = secrets_by_env.get(env)
            if secret is None:
                continue
            if secret in staged or secret in restored:
                target = credential_removed if secret in staged else credential_retained
                target.add(env)
                continue
            retirement = _retirement_tombstone(env)
            legacy = secret.with_name(secret.name + ".retiring")
            existing = (
                retirement
                if retirement.exists()
                else (legacy if legacy.exists() else None)
            )
            if existing is not None and secret.exists():
                raise MachineConfigWriteError(
                    f"credential retirement for {env!r} is ambiguous"
                )
            if _shared_secret_aliases(remaining, env=env, secret=secret):
                if existing is not None:
                    _require_owner_only(existing, env=env)
                    os.replace(existing, secret)
                    restored[secret] = (existing, env)
                credential_retained.add(env)
                continue
            if secret.exists():
                _require_owner_only(secret, env=env)
                os.replace(secret, retirement)
                staged[secret] = (retirement, env)
                credential_removed.add(env)
            elif existing is not None:
                _require_owner_only(existing, env=env)
                staged[secret] = (existing, env)
                credential_removed.add(env)
        for env in selected:
            connections.pop(env, None)
        payload["projects"] = [
            entry for entry in entries if entry.get("env") not in selected
        ]
        write_payload(payload, cfg_path, allow_unconfigured=unconfigured)
    except BaseException:
        for secret, (tombstone, _env) in reversed(tuple(staged.items())):
            os.replace(tombstone, secret)
        for secret, (tombstone, _env) in reversed(tuple(restored.items())):
            os.replace(secret, tombstone)
        raise
    for tombstone, _env in staged.values():
        tombstone.unlink()
    for tombstone, _env in recovery_tombstones:
        tombstone.unlink()
    return {
        "removed_envs": [env for env in selected if entries_by_env[env] is not None],
        "already_removed_envs": [
            env for env in selected if entries_by_env[env] is None
        ],
        "credential_removed_envs": sorted(credential_removed),
        "credential_retained_shared_envs": sorted(credential_retained),
        "project_mappings_removed": len(entries) - len(payload["projects"]),
        "active_env": str(payload.get("active_env") or ""),
        "config": str(cfg_path),
    }


def _resolve_active_authority(
    payload: dict[str, Any],
    *,
    envs: set[str],
    activate: str | None,
    connections: Mapping[str, Any],
) -> bool:
    """Move or clear ``active_env`` before selected aliases disappear.

    Returns whether the removal leaves the machine with no connections at
    all, which the config writer has to be told about explicitly.
    """
    active = str(payload.get("active_env") or "")
    if active not in envs:
        return False
    remaining = sorted(str(name) for name in connections if str(name) not in envs)
    if activate is not None:
        if activate not in remaining:
            raise MachineConfigWriteError(
                f"replacement authority {activate!r} has no entry in "
                f"connections (configured: {remaining})"
            )
        payload["active_env"] = activate
        return False
    if remaining:
        raise MachineConfigWriteError(
            f"{active!r} is this machine's active authority; name the replacement "
            f"with `--activate ENV` (configured: {remaining}) or select it "
            "first with `yoke env use ENV`"
        )
    payload.pop("active_env", None)
    return True


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
    connections: Mapping[str, Any],
    *,
    env: str,
    secret: Path | None,
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
        machine_config.yoke_home()
        / contract.SECRETS_DIR_NAME
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


__all__ = ["remove_connection", "remove_connections"]
