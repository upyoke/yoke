"""Runtime, database, path, and permission checks for machine status."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import owner_private_path
from yoke_contracts.machine_config import schema as contract
from yoke_core.domain import machine_config

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


def runtime_status(connection: Mapping[str, Any]) -> dict[str, Any]:
    imports = {name: import_status(name) for name in REQUIRED_IMPORTS}
    if connection.get("transport") in contract.POSTGRES_TRANSPORTS:
        imports["psycopg"] = import_status("psycopg")
    issues = []
    for name, item in imports.items():
        if not item["available"]:
            issues.append(
                issue(
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


def db_status(
    connection: Mapping[str, Any],
    *,
    check_reachability: bool,
) -> dict[str, Any]:
    relevant = connection.get("transport") in contract.POSTGRES_TRANSPORTS
    if not relevant:
        return {"relevant": False, "ok": None, "action": "", "issues": []}
    if not import_status("psycopg")["available"]:
        return {"relevant": True, "ok": False, "action": "import_missing", "issues": []}
    if not check_reachability:
        return {"relevant": True, "ok": None, "action": "skipped", "issues": []}
    try:
        from yoke_core.domain import connected_env_readiness as readiness

        result = readiness.status()
        issues = (
            []
            if result.ok
            else [
                issue(
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
            "issues": issues,
        }
    except Exception as exc:  # noqa: BLE001 - status reports setup failures.
        return {
            "relevant": True,
            "ok": False,
            "action": "status_error",
            "issues": [issue("error", "db_status_error", str(exc))],
        }


def path_status(raw: str | Path, label: str) -> dict[str, Any]:
    path = Path(raw).expanduser()
    exists = path.exists()
    parent = path if exists else path.parent
    writable = os.access(path if exists else parent, os.W_OK)
    issues = (
        []
        if writable
        else [
            issue(
                "error",
                f"{label}_not_writable",
                f"{label} is not writable: {path}",
                "Choose a writable path in ~/.yoke/config.json.",
            )
        ]
    )
    return {"path": str(path), "exists": exists, "writable": writable, "issues": issues}


def permission_issues(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    path_stat = path.stat()
    issues: list[dict[str, str]] = []
    if not owner_private_path.is_owner_private_file(path):
        message = f"{path} must be owner-only"
        hint = "Repair the file permissions so only your Windows account and administrators have access."
        if os.name != "nt":
            message += " (0600)"
            hint = f"Run `chmod 600 {path}`."
        issues.append(issue("error", "config_permissions", message, hint))
    if hasattr(os, "getuid") and path_stat.st_uid != os.getuid():
        issues.append(
            issue("error", "config_owner", f"{path} is not owned by the current user")
        )
    return issues


def ambient_env_status() -> dict[str, Any]:
    data = {}
    for key in AMBIENT_ENV_KEYS:
        raw = os.environ.get(key)
        data[key] = {
            "set": raw is not None,
            "value": "<redacted>" if key in SECRET_ENV_KEYS and raw else (raw or ""),
        }
    return data


def import_status(name: str) -> dict[str, Any]:
    spec = importlib.util.find_spec(name)
    return {
        "available": spec is not None,
        "origin": spec.origin if spec and spec.origin else "",
    }


def issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if hint:
        item["hint"] = hint
    return item


__all__ = [
    "ambient_env_status",
    "db_status",
    "issue",
    "path_status",
    "permission_issues",
    "runtime_status",
]
