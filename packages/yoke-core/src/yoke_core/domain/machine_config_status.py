from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yoke_core
from yoke_core.domain import machine_config
from yoke_core.domain.machine_status_diagnostics import (
    _ambient_env_status,
    _connection_status,
    _db_status,
    _issue,
    _path_status,
    _permission_issues,
    _runtime_status,
)
from yoke_contracts import install_binding as install_binding_contract
from yoke_contracts import owner_private_path
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.runtime_identity import (
    detect_install,
    human_identity_line,
    with_runtime_identity,
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
        for issue in contract.validate_payload(
            payload,
            explicit_env=explicit_env,
        )
    )
    issues.extend(_permission_issues(selected_path))
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
    db = _db_status(connection, check_reachability=check_reachability)
    issues.extend(db.pop("issues"))
    env = _ambient_env_status()
    ok = not any(issue["severity"] == "error" for issue in issues)
    owner_only = owner_private_path.is_owner_private_file(selected_path)
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
            "ambient_env": env,
        }
    )
    return report


def _install_binding() -> dict[str, Any]:
    """Install binding for the process executing ``status.run``.

    Reports where the running ``yoke_core`` package was imported from.
    A remote client's CLI binding is reported by CLI-local ``yoke status``.
    """
    return detect_install(yoke_core.__file__)


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
    identity_line = human_identity_line(report)
    if identity_line:
        lines.append(identity_line)
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
                f"    - [{issue['severity']}] {issue['code']}: {issue['message']}{hint}"
            )
    else:
        lines.append("  issues: none")
    return "\n".join(lines) + "\n"


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


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
    render_path = machine_config.board_render_path(repo_root, path=config_path)
    return {
        "repo_root": str(repo_root),
        "project_id": project_id,
        "board_settings_authority": "project-policy.settings.board",
        "board_render_path": str(render_path),
        "board_ts_path": f"{render_path}.ts",
        "board_art_path": str(machine_config.board_art_path(repo_root)),
        "board_scope": machine_config.board_scope(repo_root, path=config_path),
        "issues": issues,
    }


def _report(
    ok: bool,
    config_path: Path,
    repo_root: Path,
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    return with_runtime_identity(
        {
            "ok": ok,
            "config_path": str(config_path),
            "repo_root": str(repo_root),
            "install": _install_binding(),
            "issues": issues,
        }
    )


__all__ = ["build_status", "dumps_json", "render_human"]
