"""Machine-config writers for env, connection, auth, and project commands.

Every mutation loads ``~/.yoke/config.json`` (or seeds a fresh payload),
applies one change, validates the FULL payload against the machine-config
contract, and writes atomically with owner-only permissions. An edit that
would leave the config invalid is refused with the contract issues named —
the file on disk is never half-written.

These commands write machine-local state only, never repos or the Yoke DB.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

from yoke_cli.config import machine_config
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config.writer_credentials import (
    CredentialWriteError,
    credential_from_inputs,
)
from yoke_contracts.machine_config import schema as contract


class MachineConfigWriteError(RuntimeError):
    """The requested machine-config mutation cannot be applied."""


def set_active_env(env: str, *, path: str | Path | None = None) -> dict[str, Any]:
    """Point ``active_env`` at an already-configured connection."""
    payload, cfg_path = _load_payload(path)
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    if env not in connections:
        raise MachineConfigWriteError(
            f"env {env!r} has no entry in connections "
            f"(configured: {sorted(connections)}); add it first with "
            f"`yoke connection set {env} --transport ...`"
        )
    payload["active_env"] = env
    _write_payload(payload, cfg_path)
    return {"active_env": env, "config": str(cfg_path)}


def set_connection(
    env: str,
    *,
    transport: Optional[str] = None,
    api_url: Optional[str] = None,
    token: Optional[str] = None,
    token_file: Optional[str] = None,
    token_stdin: bool = False,
    dsn: Optional[str] = None,
    dsn_file: Optional[str] = None,
    dsn_stdin: bool = False,
    prod: Optional[bool] = None,
    replace: bool = False,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Create or update the named env's connection entry.

    Creating a new entry requires ``transport``; updates merge only the
    provided fields. ``replace=True`` discards any existing entry first
    (``transport`` required again), so no stray keys from a different
    transport shape survive the rewrite. The first configured connection
    becomes ``active_env`` (an empty config with a dangling default would
    fail validation).
    """
    payload, cfg_path = _load_payload(path)
    connections = payload.setdefault("connections", {})
    if not isinstance(connections, dict):
        raise MachineConfigWriteError("connections must be an object; repair the file first (`yoke status`)")
    if replace:
        connections.pop(env, None)
    entry = connections.get(env)
    is_new = entry is None
    if entry is None:
        if not transport:
            raise MachineConfigWriteError(
                f"env {env!r} is new; --transport is required to create it"
            )
        entry = {}
        connections[env] = entry
    if not isinstance(entry, dict):
        raise MachineConfigWriteError(f"connections.{env} must be an object")
    if transport:
        entry["transport"] = transport
    if api_url:
        entry["api_url"] = api_url
    if prod is not None:
        entry[contract.PROD_FLAG_KEY] = prod
    elif (
        (is_new or contract.PROD_FLAG_KEY not in entry)
        and str(entry.get("transport") or "").strip() in contract.POSTGRES_TRANSPORTS
    ):
        entry[contract.PROD_FLAG_KEY] = False
    try:
        source = credential_from_inputs(
            env,
            token=token,
            token_file=token_file,
            token_stdin=token_stdin,
            dsn=dsn,
            dsn_file=dsn_file,
            dsn_stdin=dsn_stdin,
            require_one=False,
        )
    except CredentialWriteError as exc:
        raise MachineConfigWriteError(str(exc)) from exc
    if source:
        entry["credential_source"] = source
    if not str(payload.get("active_env") or "").strip():
        payload["active_env"] = env
    _write_payload(payload, cfg_path)
    return {"env": env, "connection": dict(entry),
            "active_env": payload["active_env"], "config": str(cfg_path)}


def set_credential(
    env: str,
    *,
    token: Optional[str] = None,
    token_file: Optional[str] = None,
    token_stdin: bool = False,
    dsn: Optional[str] = None,
    dsn_file: Optional[str] = None,
    dsn_stdin: bool = False,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Set or rotate the named env's credential_source.

    Secret inputs become Yoke-owned machine credential refs in owner-only
    file storage. The config stores the ref, never the raw value or arbitrary
    source path.
    """
    payload, cfg_path = _load_payload(path)
    connections = payload.get("connections")
    connections = connections if isinstance(connections, dict) else {}
    entry = connections.get(env)
    if not isinstance(entry, dict):
        raise MachineConfigWriteError(
            f"env {env!r} has no entry in connections "
            f"(configured: {sorted(connections)}); create it first with "
            f"`yoke connection set {env} --transport ...`"
        )
    try:
        entry["credential_source"] = credential_from_inputs(
            env,
            token=token,
            token_file=token_file,
            token_stdin=token_stdin,
            dsn=dsn,
            dsn_file=dsn_file,
            dsn_stdin=dsn_stdin,
            require_one=True,
        )
    except CredentialWriteError as exc:
        raise MachineConfigWriteError(str(exc)) from exc
    _write_payload(payload, cfg_path)
    return {"env": env, "credential_source": dict(entry["credential_source"]),
            "config": str(cfg_path)}


def register_project(
    repo_root: str | Path,
    project_id: int,
    *,
    board_scope: Optional[str] = None,
    board_render_path: Optional[str] = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Map a local checkout path to its DB project id."""
    root = Path(repo_root).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    if not root.is_dir():
        raise MachineConfigWriteError(f"checkout path is not a directory: {root}")
    normalized = contract.normalize_project_id(project_id)
    if normalized is None:
        raise MachineConfigWriteError("--project-id must be a positive integer")
    payload, cfg_path = _load_payload(path)
    env = _registration_env(payload)
    # Project ids are per universe, so the mapping records the id per env: the
    # (checkout, env) row is upserted, leaving the checkout's rows for other
    # envs intact.
    board = {k: v for k, v in (
        ("scope", board_scope), ("render_path", board_render_path),
    ) if v}
    payload["projects"] = contract.upsert_project_entry(
        payload.get("projects"), checkout=str(root),
        project_id=normalized, env=env, board=board or None,
    )
    _write_payload(payload, cfg_path)
    written = next(
        (e for e in payload["projects"]
         if e.get("checkout") == str(root) and e.get("env") == env),
        {},
    )
    return {"checkout": str(root), "entry": written, "config": str(cfg_path)}


def stamp_untagged_project_envs(
    env: str | None = None,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Stamp ``env`` onto every untagged ``projects`` entry; log each stamp.

    The creating env cannot be recovered from an untagged legacy entry, so
    the operator chooses one via ``--env`` (default: the machine's current
    ``active_env``). Already-tagged entries are left untouched. Normalizes a
    legacy checkout-keyed object into the canonical flat list. The full
    stamped payload is validated before it is written, so a bogus env is
    refused rather than landing an invalid config.
    """
    payload, cfg_path = _load_payload(path)
    env = env if _nonempty(env) else _registration_env(payload)
    connections = payload.get("connections")
    labels = set(connections) if isinstance(connections, dict) else set()
    if env not in labels:
        raise MachineConfigWriteError(
            f"env {env!r} has no entry in connections (configured: "
            f"{sorted(labels)}); pass a configured env via --env or add one "
            "first with `yoke connection set ENV --transport ...`"
        )
    entries = contract.normalize_projects(payload.get("projects"))
    stamped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in entries:
        if _nonempty(entry.get("env")):
            skipped.append({"checkout": entry["checkout"], "env": entry["env"]})
            continue
        entry["env"] = env
        stamped.append({
            "checkout": entry["checkout"], "env": env,
            "project_id": entry["project_id"],
        })
    payload["projects"] = entries
    _write_payload(payload, cfg_path)
    return {"env": env, "stamped": stamped, "skipped": skipped,
            "config": str(cfg_path)}


def _registration_env(payload: Mapping[str, Any]) -> str:
    """Resolve the connection env a project mapping is being written under."""
    try:
        return contract.selected_env(payload)
    except contract.MachineConfigContractError as exc:
        raise MachineConfigWriteError(
            "cannot record a project mapping without a resolvable connection "
            "env; add one first with `yoke connection set ENV --transport ...`"
        ) from exc


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def set_runtime_paths(
    *,
    temp_root: str | Path,
    cache_dir: str | Path,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Set machine-local runtime dirs explicitly."""
    payload, cfg_path = _load_payload(path)
    payload["temp_root"] = str(temp_root)
    payload["cache_dir"] = str(cache_dir)
    _write_payload(payload, cfg_path)
    return {
        "temp_root": payload["temp_root"],
        "cache_dir": payload["cache_dir"],
        "config": str(cfg_path),
    }


def set_github(
    *,
    credential_source: Mapping[str, Any],
    api_url: str,
    verified_login: str | None = None,
    verified_user_id: int | None = None,
    scopes: list[str] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Set the machine-level GitHub credential reference."""
    payload, cfg_path = _load_payload(path)
    entry: dict[str, Any] = {
        "api_url": api_url,
        "credential_source": dict(credential_source),
    }
    if verified_login:
        entry["verified_login"] = verified_login
    if verified_user_id is not None:
        entry["verified_user_id"] = verified_user_id
    if scopes is not None:
        entry["scopes"] = sorted(scopes)
    payload["github"] = entry
    _write_payload(payload, cfg_path)
    return {"github": dict(entry), "config": str(cfg_path)}


def store_github_token(secret: str) -> Path:
    """Store the machine GitHub PAT under the Yoke secrets directory."""
    try:
        return machine_secrets.store_github_token(secret)
    except machine_secrets.MachineSecretError as exc:
        raise MachineConfigWriteError(str(exc)) from exc


def _load_payload(path: str | Path | None) -> tuple[dict[str, Any], Path]:
    cfg_path = machine_config.config_path(path)
    payload = machine_config.load_config(path)
    if not payload:
        payload = {"schema_version": contract.SCHEMA_VERSION}
    return payload, cfg_path


def _write_payload(payload: dict[str, Any], cfg_path: Path) -> None:
    errors = [issue for issue in contract.validate_payload(payload)
              if issue.severity == "error"]
    if errors:
        detail = "\n".join(
            f"  - {issue.code}: {issue.message}"
            + (f" ({issue.path})" if issue.path else "")
            for issue in errors
        )
        raise MachineConfigWriteError(
            f"refusing to write invalid machine config:\n{detail}"
        )
    cfg_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = cfg_path.with_name(cfg_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp_path.chmod(0o600)
    os.replace(tmp_path, cfg_path)


__all__ = ["MachineConfigWriteError", "register_project",
           "stamp_untagged_project_envs", "set_github",
           "set_runtime_paths", "set_active_env", "set_connection",
           "set_credential", "store_github_token"]
