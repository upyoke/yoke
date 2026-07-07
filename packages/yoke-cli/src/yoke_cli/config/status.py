"""Product-wheel ``yoke status`` implementation.

This product version validates machine config, project mapping, credentials,
and the import surface available to the installed CLI. Local-Postgres admin
envs are legitimate local-core authority: status reports whether the required
source-dev runtime is present instead of treating those envs as refused.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.api_urls import HEALTH_PATH, join_api_url
from yoke_cli.config import install_binding, machine_config
from yoke_cli.config.status_credentials import (
    credential_status as _credential_status,
)
from yoke_cli.config.status_environment import (
    ambient_env_status,
    permission_issues,
)
from yoke_cli.config.status_render import dumps_json, render_human
from yoke_contracts.engine_version import ENGINE_DISTRIBUTION_NAME
from yoke_contracts.machine_config import schema as contract


REQUIRED_IMPORTS = ("yoke_cli", "yoke_contracts", "pydantic", "pyfiglet")
PRODUCT_RUNTIME_PACKAGES = (
    install_binding.CLI_DISTRIBUTION_NAME,
    "yoke-contracts",
    "yoke-harness",
    ENGINE_DISTRIBUTION_NAME,
)

#: Timeout for the one ``GET /v1/health`` probe an https ``yoke status`` runs.
SERVER_HEALTH_TIMEOUT_S = 3.0


def build_status(
    *,
    config_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    explicit_env: str | None = None,
    check_reachability: bool = True,
) -> dict[str, Any]:
    selected_path = machine_config.config_path(config_path)
    selected_repo = Path(repo_root).expanduser() if repo_root else Path.cwd()
    issues: list[dict[str, str]] = []
    try:
        payload = machine_config.load_config(selected_path)
    except machine_config.MachineConfigError as exc:
        return _report(
            False,
            selected_path,
            selected_repo,
            issues
            + [
                _issue(
                    "error",
                    "config_json",
                    str(exc),
                    "Fix JSON syntax or regenerate from `yoke config example`.",
                )
            ],
        )
    if not selected_path.is_file():
        issues.append(
            _issue(
                "error",
                "config_missing",
                f"machine config not found at {selected_path}",
                "Create it from `yoke config example > ~/.yoke/config.json`.",
            )
        )
    issues.extend(
        issue.as_dict()
        for issue in contract.validate_payload(payload, explicit_env=explicit_env)
    )
    issues.extend(permission_issues(selected_path))
    normalized = contract.normalize_payload(payload)
    connection, connection_issues = _connection_status(
        normalized,
        config_path=selected_path,
        explicit_env=explicit_env,
    )
    issues.extend(connection_issues)
    temp = _path_status(machine_config.temp_root(selected_path), "temp_root")
    cache = _path_status(machine_config.cache_dir(selected_path), "cache_dir")
    issues.extend(temp.pop("issues"))
    issues.extend(cache.pop("issues"))
    project = _project_status(selected_repo, selected_path)
    issues.extend(project.pop("issues"))
    runtime = _runtime_status(connection)
    issues.extend(runtime.pop("issues"))
    db = _db_status(connection, runtime=runtime, check_reachability=check_reachability)
    issues.extend(db.pop("issues"))
    server = _server_status(connection, check_reachability=check_reachability)
    issues.extend(server.pop("issues"))
    env = ambient_env_status()
    ok = not any(issue["severity"] == "error" for issue in issues)
    owner_only = selected_path.is_file() and not (selected_path.stat().st_mode & 0o077)
    report = _report(ok, selected_path, selected_repo, issues)
    report.update(
        {
            "config": {
                "path": str(selected_path),
                "exists": selected_path.is_file(),
                "owner_only": bool(owner_only),
            },
            "connection": connection,
            "paths": {"temp_root": temp, "cache_dir": cache},
            "project": project,
            "runtime": runtime,
            "db": db,
            "server": server,
            "ambient_env": env,
        }
    )
    return report


def _connection_status(
    payload: Mapping[str, Any],
    *,
    config_path: Path,
    explicit_env: str | None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    raw_connections = payload.get("connections")
    available = (
        sorted(map(str, raw_connections)) if isinstance(raw_connections, Mapping) else []
    )
    connection: Mapping[str, Any] = {}
    try:
        connection = contract.active_connection(payload, explicit_env=explicit_env)
    except contract.MachineConfigContractError as exc:
        issues.append(_issue("error", "active_env", str(exc)))
    source = connection.get("credential_source")
    source = source if isinstance(source, Mapping) else {}
    credential = _credential_status(source, config_path=config_path)
    issues.extend(credential.pop("issues"))
    authority = connection.get("authority")
    transport = str(connection.get("transport") or "")
    status = {
        "env": str(connection.get("env") or ""),
        "envs": available,
        "transport": transport,
        "prod": _connection_prod_flag(connection),
        "api_url": connection.get("api_url") or "",
        "authority_kind": (
            str(authority.get("kind") or "")
            if isinstance(authority, Mapping)
            else ""
        ),
        "credential_source": credential,
        "client_authority": (
            "local-core" if transport in contract.POSTGRES_TRANSPORTS else "api"
        ),
    }
    return status, issues


def _connection_prod_flag(connection: Mapping[str, Any]) -> bool | None:
    value = connection.get(contract.PROD_FLAG_KEY)
    return value if isinstance(value, bool) else None


def _project_status(repo_root: Path, config_path: Path) -> dict[str, Any]:
    project_id = machine_config.project_id(repo_root, config_path)
    issues: list[dict[str, str]] = []
    if project_id is None:
        issues.append(
            _issue(
                "warning",
                "project_mapping_missing",
                f"checkout {repo_root} is not mapped to a project_id",
                "Project-scoped commands need `yoke project register` first.",
            )
        )
    render = machine_config.board_render_path(repo_root, path=config_path)
    return {
        "repo_root": str(repo_root),
        "project_id": project_id,
        "board_config_path": str(repo_root / ".yoke" / "board.json"),
        "board_render_path": str(render),
        "board_ts_path": f"{render}.ts",
        "board_art_path": str(machine_config.board_art_path(repo_root)),
        "board_scope": machine_config.board_scope(repo_root, path=config_path),
        "issues": issues,
    }


def _runtime_status(connection: Mapping[str, Any]) -> dict[str, Any]:
    imports = {name: _import_status(name) for name in REQUIRED_IMPORTS}
    if connection.get("transport") in contract.POSTGRES_TRANSPORTS:
        imports["yoke_core"] = _import_status("yoke_core")
        imports["psycopg"] = _import_status("psycopg")
    package_versions = {
        name: _package_version(name) for name in PRODUCT_RUNTIME_PACKAGES
    }
    issues = []
    for name, item in imports.items():
        if not item["available"]:
            hint = (
                "Repair the install so the yoke-core engine and psycopg "
                "import (local-postgres connections dispatch in-process), "
                "or switch to an HTTPS env."
                if name in {"yoke_core", "psycopg"}
                else "Install the Yoke product packages."
            )
            issues.append(
                _issue(
                    "error",
                    "import_missing",
                    f"required package import failed: {name}",
                    hint,
                )
            )
    return {
        "python_executable": sys.executable,
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "yoke_executable": shutil.which("yoke") or "",
        "imports": imports,
        "package_versions": package_versions,
        "issues": issues,
    }


def _package_version(name: str) -> str:
    try:
        return package_version(name)
    except PackageNotFoundError:
        return ""


def _db_status(
    connection: Mapping[str, Any],
    *,
    runtime: Mapping[str, Any],
    check_reachability: bool,
) -> dict[str, Any]:
    relevant = connection.get("transport") in contract.POSTGRES_TRANSPORTS
    if not relevant:
        return {"relevant": False, "ok": None, "action": "", "issues": []}
    imports = runtime.get("imports")
    imports = imports if isinstance(imports, Mapping) else {}
    core_available = _import_available(imports, "yoke_core")
    psycopg_available = _import_available(imports, "psycopg")
    if not core_available:
        return {
            "relevant": True,
            "ok": False,
            "action": "local_postgres_core_unavailable",
            "issues": [],
        }
    if not psycopg_available:
        return {
            "relevant": True,
            "ok": False,
            "action": "local_postgres_driver_unavailable",
            "issues": [],
        }
    if not check_reachability:
        return {"relevant": True, "ok": None, "action": "skipped", "issues": []}
    return {
        "relevant": True,
        "ok": True,
        "action": "local_postgres_admin_env",
        "issues": [],
    }


def _fetch_server_health(
    api_url: str, *, timeout_s: float = SERVER_HEALTH_TIMEOUT_S,
) -> Mapping[str, Any] | None:
    """One ``GET /v1/health`` against the active env; ``None`` on any failure."""
    import urllib.request

    url = join_api_url(api_url, HEALTH_PATH)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - unreachable server degrades, never raises
        return None
    return payload if isinstance(payload, dict) else None


def _server_status(
    connection: Mapping[str, Any], *, check_reachability: bool,
) -> dict[str, Any]:
    """The active https server's advertised engine version, via one health call.

    Irrelevant for local-postgres transports (there is no server). Degrades
    gracefully: an unreachable server yields ``reachable=False`` plus a
    warning issue — never an error, never an exception.
    """
    if str(connection.get("transport") or "") != contract.TRANSPORT_HTTPS:
        return {"relevant": False, "reachable": None, "engine_version": "",
                "issues": []}
    api_url = str(connection.get("api_url") or "")
    if not api_url or not check_reachability:
        return {"relevant": True, "reachable": None, "engine_version": "",
                "issues": []}
    payload = _fetch_server_health(api_url)
    if payload is None:
        return {
            "relevant": True,
            "reachable": False,
            "engine_version": "",
            "issues": [
                _issue(
                    "warning",
                    "server_unreachable",
                    f"health probe failed against {api_url}",
                    "Check the api_url and network; the server may be down.",
                )
            ],
        }
    return {
        "relevant": True,
        "reachable": True,
        "engine_version": str(payload.get("engine_version") or ""),
        "build": str(payload.get("build") or ""),
        "issues": [],
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
    return {
        "path": str(path),
        "exists": exists,
        "writable": writable,
        "issues": issues,
    }


def _import_status(name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(name)
    except ImportError as exc:
        return {"available": False, "origin": "", "error": str(exc)}
    return {"available": spec is not None,
            "origin": spec.origin if spec and spec.origin else ""}


def _import_available(imports: Mapping[str, Any], name: str) -> bool:
    item = imports.get(name)
    return bool(item.get("available")) if isinstance(item, Mapping) else False


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if hint:
        item["hint"] = hint
    return item


def _report(
    ok: bool,
    config_path: Path,
    repo_root: Path,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    return {"ok": ok, "config_path": str(config_path),
            "repo_root": str(repo_root),
            "install": install_binding.detect(), "issues": issues}


__all__ = ["build_status", "dumps_json", "render_human"]
