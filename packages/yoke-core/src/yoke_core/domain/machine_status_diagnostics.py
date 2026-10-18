"""Machine configuration, credential, runtime and path diagnostics."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain import machine_config
from yoke_contracts import owner_private_path
from yoke_contracts.machine_config import schema as contract

REQUIRED_IMPORTS = ("fastapi", "uvicorn", "pydantic", "nacl")
SECRET_ENV_KEYS = {"YOKE_PG_DSN"}
AMBIENT_ENV_KEYS = (
    machine_config.CONFIG_FILE_ENV,
    machine_config.HOME_ENV,
    contract.ENV_OVERRIDE,
    "YOKE_PROJECT",
    "YOKE_PG_DSN",
    "YOKE_PG_DSN_FILE",
    "YOKE_SCRATCH_ROOT",
    "YOKE_CONNECTED_ENV_DISABLE",
)


def _connection_status(
    payload: Mapping[str, Any],
    *,
    config_path: Path,
    explicit_env: str | None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    raw_connections = payload.get("connections")
    available = (
        sorted(map(str, raw_connections))
        if isinstance(raw_connections, Mapping)
        else []
    )
    connection: Mapping[str, Any] = {}
    try:
        connection = contract.active_connection(payload, explicit_env=explicit_env)
    except contract.MachineConfigContractError as exc:
        issues.append(_issue("error", "active_env", str(exc)))
    source = connection.get("credential_source")
    credential = _credential_status(
        source if isinstance(source, Mapping) else {},
        config_path=config_path,
    )
    issues.extend(credential.pop("issues"))
    authority = connection.get("authority")
    return (
        {
            "env": str(connection.get("env") or ""),
            "envs": available,
            "transport": str(connection.get("transport") or ""),
            "api_url": connection.get("api_url") or "",
            "authority_kind": (
                str(authority.get("kind") or "")
                if isinstance(authority, Mapping)
                else ""
            ),
            "credential_source": credential,
        },
        issues,
    )


def _credential_status(
    source: Mapping[str, Any],
    *,
    config_path: Path,
) -> dict[str, Any]:
    kind = str(source.get("kind") or "")
    issues: list[dict[str, str]] = []
    status: dict[str, Any] = {"kind": kind or None, "present": False}
    if kind in ("dsn_file", "token_file"):
        raw = str(source.get("path") or "")
        path = Path(raw).expanduser()
        if raw and not path.is_absolute():
            path = config_path.parent / path
        status.update({"path": str(path), "present": path.is_file()})
        if not path.is_file():
            label = "DSN" if kind == "dsn_file" else "token"
            issues.append(
                _issue(
                    "error",
                    "credential_missing",
                    f"{label} file is missing: {path}",
                    "Create the file with owner-only permissions.",
                )
            )
    elif kind == "env":
        name = str(source.get("name") or "")
        status.update({"name": name, "present": bool(os.environ.get(name))})
        if not os.environ.get(name):
            issues.append(
                _issue(
                    "error",
                    "credential_env_missing",
                    f"credential env var is unset: {name}",
                    "Set the variable before running Yoke.",
                )
            )
    elif kind == "aws_secrets_manager":
        status["present"] = True
    elif kind:
        issues.append(
            _issue(
                "error",
                "credential_kind_unknown",
                f"unsupported credential kind: {kind}",
            )
        )
    status["issues"] = issues
    return status


def _runtime_status(connection: Mapping[str, Any]) -> dict[str, Any]:
    imports = {name: _import_status(name) for name in REQUIRED_IMPORTS}
    if connection.get("transport") in contract.POSTGRES_TRANSPORTS:
        imports["psycopg"] = _import_status("psycopg")
    issues = []
    for name, item in imports.items():
        if not item["available"]:
            issues.append(
                _issue(
                    "error",
                    "import_missing",
                    f"required package import failed: {name}",
                    "Install project dependencies.",
                )
            )
    origin_spec = importlib.util.find_spec("runtime")
    return {
        "python_executable": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "yoke_executable": shutil.which("yoke") or "",
        "runtime_import_origin": (
            origin_spec.origin if origin_spec and origin_spec.origin else ""
        ),
        "imports": imports,
        "issues": issues,
    }


def _db_status(
    connection: Mapping[str, Any],
    *,
    check_reachability: bool,
) -> dict[str, Any]:
    relevant = connection.get("transport") in contract.POSTGRES_TRANSPORTS
    if not relevant:
        return {"relevant": False, "ok": None, "action": "", "issues": []}
    psycopg_status = _import_status("psycopg")
    if not psycopg_status["available"]:
        return {"relevant": True, "ok": False, "action": "import_missing", "issues": []}
    if not check_reachability:
        return {"relevant": True, "ok": None, "action": "skipped", "issues": []}
    try:
        from yoke_core.domain import connected_env_readiness as readiness

        result = readiness.status()
        issue = (
            []
            if result.ok
            else [
                _issue(
                    "error",
                    "db_unreachable",
                    result.message,
                    "Repair the configured credential/tunnel, then rerun yoke status.",
                )
            ]
        )
        return {
            "relevant": True,
            "ok": result.ok,
            "action": result.action,
            "connector_kind": result.connector_kind,
            "issues": issue,
        }
    except Exception as exc:  # noqa: BLE001 - status must report setup failures.
        return {
            "relevant": True,
            "ok": False,
            "action": "status_error",
            "issues": [_issue("error", "db_status_error", str(exc))],
        }


def _path_status(raw: str | Path, label: str) -> dict[str, Any]:
    path = Path(raw).expanduser()
    exists = path.exists()
    parent = path if exists else path.parent
    writable = os.access(path if exists else parent, os.W_OK)
    issues = (
        []
        if writable
        else [
            _issue(
                "error",
                f"{label}_not_writable",
                f"{label} is not writable: {path}",
                "Choose a writable path in ~/.yoke/config.json.",
            )
        ]
    )
    return {"path": str(path), "exists": exists, "writable": writable, "issues": issues}


def _permission_issues(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    stat = path.stat()
    issues: list[dict[str, str]] = []
    if not owner_private_path.is_owner_private_file(path):
        message = f"{path} must be owner-only"
        hint = (
            "Repair the file permissions so only your Windows account and "
            "administrators have access."
        )
        if os.name != "nt":
            message += " (0600)"
            hint = f"Run `chmod 600 {path}`."
        issues.append(
            _issue(
                "error",
                "config_permissions",
                message,
                hint,
            )
        )
    if hasattr(os, "getuid") and stat.st_uid != os.getuid():
        issues.append(
            _issue("error", "config_owner", f"{path} is not owned by the current user")
        )
    return issues


def _ambient_env_status() -> dict[str, Any]:
    data = {}
    for key in AMBIENT_ENV_KEYS:
        raw = os.environ.get(key)
        data[key] = {
            "set": raw is not None,
            "value": "<redacted>" if key in SECRET_ENV_KEYS and raw else (raw or ""),
        }
    return data


def _import_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    return {
        "available": spec is not None,
        "origin": spec.origin if spec and spec.origin else "",
    }


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if hint:
        item["hint"] = hint
    return item
