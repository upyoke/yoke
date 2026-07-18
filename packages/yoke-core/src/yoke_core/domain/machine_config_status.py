from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import yoke_core
from yoke_core.domain import machine_config
from yoke_contracts import install_binding as install_binding_contract
from yoke_contracts.engine_version import ENGINE_DISTRIBUTION_NAME
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
        return _report(False, selected_path, selected_repo, issues + [
            _issue("error", "config_json", str(exc),
                   "Fix JSON syntax or regenerate from `yoke config example`.")
        ])
    if not selected_path.is_file():
        issues.append(_issue(
            "error", "config_missing",
            f"machine config not found at {selected_path}",
            "Create it from `yoke config example > ~/.yoke/config.json`.",
        ))
    issues.extend(issue.as_dict() for issue in contract.validate_payload(
        payload, explicit_env=explicit_env,
    ))
    issues.extend(_permission_issues(selected_path))
    normalized = contract.normalize_payload(payload)
    connection, connection_issues = _connection_status(
        normalized, config_path=selected_path, explicit_env=explicit_env,
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
    db = _db_status(connection, check_reachability=check_reachability)
    issues.extend(db.pop("issues"))
    env = _ambient_env_status()
    ok = not any(issue["severity"] == "error" for issue in issues)
    owner_only = selected_path.is_file() and not (selected_path.stat().st_mode & 0o077)
    report = _report(ok, selected_path, selected_repo, issues)
    report.update({
        "config": {"path": str(selected_path), "exists": selected_path.is_file(),
                   "owner_only": bool(owner_only)},
        "connection": connection,
        "paths": {"temp_root": temp, "cache_dir": cache},
        "project": project,
        "runtime": runtime,
        "db": db,
        "ambient_env": env,
    })
    return report


def _install_binding() -> dict[str, Any]:
    """Install binding of the process executing this handler.

    ``status.run`` dispatch runs this twin wherever the function call
    executes — the caller's own process for in-process dispatch, the
    server process over the HTTP function-call surface. Every field in
    this report (runtime imports, ambient env, config path) describes
    that executing process, so the install binding does too: it reports
    where the running ``yoke_core`` package was imported from. A remote
    client's CLI binding is unknowable here; that binding is reported by
    the CLI-local ``yoke status``.
    """
    resolved = Path(yoke_core.__file__)
    checkout_root = install_binding_contract.source_checkout_root(resolved)
    version = install_binding_contract.distribution_version_for_module(
        ENGINE_DISTRIBUTION_NAME,
        resolved,
    )
    return {
        "kind": (install_binding_contract.KIND_SOURCE_CHECKOUT if checkout_root
                 else install_binding_contract.KIND_PACKAGED_WHEEL),
        "checkout_root": str(checkout_root) if checkout_root else None,
        "module_origin": str(resolved),
        "version": version,
    }

def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "Yoke status",
        f"  ok: {str(report.get('ok')).lower()}",
        f"  config: {report.get('config_path')}",
        f"  checkout: {report.get('repo_root')}",
    ]
    install = report.get("install")
    if isinstance(install, Mapping):
        lines.append(f"  install: {install_binding_contract.label(install)}")
    connection = report.get("connection") or {}
    if isinstance(connection, Mapping):
        lines.append(
            "  connection: "
            f"env={connection.get('env') or '<missing>'} "
            f"transport={connection.get('transport') or '<missing>'} "
            f"credential={connection.get('credential_source', {}).get('kind') or '<missing>'} "
            f"envs={','.join(connection.get('envs') or []) or '<none>'}"
        )
    project = report.get("project") or {}
    if isinstance(project, Mapping):
        lines.append(
            "  project: "
            f"id={project.get('project_id') or '<missing>'} "
            f"scope={project.get('board_scope') or '<missing>'} "
            f"board={project.get('board_render_path') or '<missing>'}"
        )
    runtime = report.get("runtime") or {}
    if isinstance(runtime, Mapping):
        lines.append(
            "  runtime: "
            f"python={runtime.get('python_version')} "
            f"yoke={runtime.get('yoke_executable') or '<not on PATH>'}"
        )
    db = report.get("db") or {}
    if isinstance(db, Mapping):
        lines.append(
            "  db: "
            f"relevant={db.get('relevant')} "
            f"ok={db.get('ok')} "
            f"action={db.get('action') or '<none>'}"
        )
    issues = list(report.get("issues") or [])
    if issues:
        lines.append("  issues:")
        for issue in issues:
            hint = f" Hint: {issue['hint']}" if issue.get("hint") else ""
            lines.append(
                f"    - [{issue['severity']}] {issue['code']}: "
                f"{issue['message']}{hint}"
            )
    else:
        lines.append("  issues: none")
    return "\n".join(lines) + "\n"


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"

def _connection_status(
    payload: Mapping[str, Any],
    *,
    config_path: Path,
    explicit_env: str | None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    raw_connections = payload.get("connections")
    available = (sorted(map(str, raw_connections))
                 if isinstance(raw_connections, Mapping) else [])
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
    return ({
        "env": str(connection.get("env") or ""),
        "envs": available,
        "transport": str(connection.get("transport") or ""),
        "api_url": connection.get("api_url") or "",
        "authority_kind": (str(authority.get("kind") or "")
                           if isinstance(authority, Mapping) else ""),
        "credential_source": credential,
    }, issues)

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
            issues.append(_issue("error", "credential_missing",
                                 f"{label} file is missing: {path}",
                                 "Create the file with owner-only permissions."))
    elif kind == "env":
        name = str(source.get("name") or "")
        status.update({"name": name, "present": bool(os.environ.get(name))})
        if not os.environ.get(name):
            issues.append(_issue("error", "credential_env_missing",
                                 f"credential env var is unset: {name}",
                                 "Set the variable before running Yoke."))
    elif kind == "aws_secrets_manager":
        status["present"] = True
    elif kind:
        issues.append(_issue("error", "credential_kind_unknown",
                             f"unsupported credential kind: {kind}"))
    status["issues"] = issues
    return status


def _project_status(repo_root: Path, config_path: Path) -> dict[str, Any]:
    entry = machine_config.project_entry(repo_root, config_path)
    project_id = machine_config.project_id(repo_root, config_path)
    issues: list[dict[str, str]] = []
    if project_id is None:
        issues.append(_issue(
            "error", "project_mapping_missing",
            f"checkout {repo_root} is not mapped to a project_id",
            "Add this checkout path to projects in ~/.yoke/config.json.",
        ))
    render_path = machine_config.board_render_path(repo_root, path=config_path)
    return {
        "repo_root": str(repo_root),
        "project_id": project_id,
        "board_config_path": str(repo_root / ".yoke" / "board.json"),
        "board_render_path": str(render_path),
        "board_ts_path": f"{render_path}.ts",
        "board_art_path": str(machine_config.board_art_path(repo_root)),
        "board_scope": machine_config.board_scope(repo_root, path=config_path),
        "issues": issues,
    }


def _runtime_status(connection: Mapping[str, Any]) -> dict[str, Any]:
    imports = {name: _import_status(name) for name in REQUIRED_IMPORTS}
    if connection.get("transport") in contract.POSTGRES_TRANSPORTS:
        imports["psycopg"] = _import_status("psycopg")
    issues = []
    for name, item in imports.items():
        if not item["available"]:
            issues.append(_issue("error", "import_missing",
                                 f"required package import failed: {name}",
                                 "Install project dependencies."))
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
        return {"relevant": True, "ok": False, "action": "import_missing",
                "issues": []}
    if not check_reachability:
        return {"relevant": True, "ok": None, "action": "skipped", "issues": []}
    try:
        from yoke_core.domain import connected_env_readiness as readiness

        result = readiness.status()
        issue = [] if result.ok else [_issue(
            "error", "db_unreachable", result.message,
            "Repair the configured credential/tunnel, then rerun yoke status.",
        )]
        return {"relevant": True, "ok": result.ok, "action": result.action,
                "connector_kind": result.connector_kind, "issues": issue}
    except Exception as exc:  # noqa: BLE001 - status must report setup failures.
        return {"relevant": True, "ok": False, "action": "status_error",
                "issues": [_issue("error", "db_status_error", str(exc))]}


def _path_status(raw: str | Path, label: str) -> dict[str, Any]:
    path = Path(raw).expanduser()
    exists = path.exists()
    parent = path if exists else path.parent
    writable = os.access(path if exists else parent, os.W_OK)
    issues = [] if writable else [_issue(
        "error", f"{label}_not_writable",
        f"{label} is not writable: {path}",
        "Choose a writable path in ~/.yoke/config.json.",
    )]
    return {"path": str(path), "exists": exists, "writable": writable,
            "issues": issues}


def _permission_issues(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    stat = path.stat()
    issues: list[dict[str, str]] = []
    if stat.st_mode & 0o077:
        issues.append(_issue("error", "config_permissions",
                             f"{path} must be owner-only (0600)",
                             f"Run `chmod 600 {path}`."))
    if hasattr(os, "getuid") and stat.st_uid != os.getuid():
        issues.append(_issue("error", "config_owner",
                             f"{path} is not owned by the current user"))
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
    return {"available": spec is not None,
            "origin": spec.origin if spec and spec.origin else ""}


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
            "install": _install_binding(), "issues": issues}

__all__ = ["build_status", "dumps_json", "render_human"]
