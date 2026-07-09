"""Detect already-applied machine and project onboarding state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project
from yoke_cli.config import project_clone_resume
from yoke_cli.project_install import files as project_install_files


def detect(
    *,
    cfg_path: Path,
    env_name: str,
    api_url: str,
    credential_source: Mapping[str, Any],
    source: Mapping[str, Any],
    project_inputs: Mapping[str, Any],
    machine_github: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _load_machine_payload(cfg_path)
    connection = _connection_entry(payload, env_name)
    planned_token_path = _path_text(credential_source.get("path"))
    source_token_path = _path_text(source.get("path"))
    temp_root = cfg_path.parent / "tmp"
    cache_dir = cfg_path.parent / "cache"
    checkout = project_inputs.get("checkout")
    project_id = _positive_int(project_inputs.get("existing_project_id"))
    mode = str(project_inputs.get("mode") or "")
    remote_url = str(project_inputs.get("remote_url") or "")
    return {
        "yoke_home": cfg_path.parent.is_dir(),
        "active_env": str(payload.get("active_env") or "") == env_name,
        "connection": _connection_matches(connection, api_url),
        "token_reference": (
            _credential_source_matches(connection, credential_source)
            and planned_token_path
            and source_token_path == planned_token_path
            and Path(planned_token_path).expanduser().is_file()
        ),
        "machine_github": _machine_github_matches(payload, machine_github),
        "temp_root": (
            _effective_path(machine_config.temp_root(cfg_path)) == _effective_path(temp_root)
            and temp_root.is_dir()
        ),
        "cache_dir": (
            _effective_path(machine_config.cache_dir(cfg_path)) == _effective_path(cache_dir)
            and cache_dir.is_dir()
        ),
        "project_identity": project_id is not None,
        "project_checkout": _project_checkout_reused(cfg_path, checkout, project_id),
        "project_github_auth": (
            project_id is not None or bool(project_inputs.get("keep_existing_remote"))
        ),
        "project_existing_remote": bool(project_inputs.get("keep_existing_remote")),
        "project_clone_checkout": _project_clone_checkout_reused(
            checkout, remote_url, mode,
        ),
        "project_scaffold": _project_scaffold_installed(checkout, project_id),
    }


def _load_machine_payload(cfg_path: Path) -> dict[str, Any]:
    try:
        return machine_config.load_config(cfg_path)
    except machine_config.MachineConfigError:
        return {}


def _connection_entry(payload: Mapping[str, Any], env_name: str) -> Mapping[str, Any]:
    connections = payload.get("connections")
    if not isinstance(connections, Mapping):
        return {}
    entry = connections.get(env_name)
    return entry if isinstance(entry, Mapping) else {}


def _connection_matches(connection: Mapping[str, Any], api_url: str) -> bool:
    return (
        str(connection.get("transport") or "") == "https"
        and _clean_url(connection.get("api_url")) == _clean_url(api_url)
    )


def _credential_source_matches(
    connection: Mapping[str, Any],
    planned: Mapping[str, Any],
) -> bool:
    source = connection.get("credential_source")
    if not isinstance(source, Mapping):
        return False
    return (
        str(source.get("kind") or "") == str(planned.get("kind") or "")
        and _path_text(source.get("path")) == _path_text(planned.get("path"))
    )


def _machine_github_matches(
    payload: Mapping[str, Any],
    machine_github: Mapping[str, Any],
) -> bool:
    if str(machine_github.get("choice") or "") != onboard_machine_github.CHOICE_CONNECT:
        return False
    github = payload.get("github")
    if not isinstance(github, Mapping):
        return False
    authorization_source = machine_github.get("authorization_source")
    if not isinstance(authorization_source, Mapping):
        return False
    authorization = github.get("authorization")
    if not isinstance(authorization, Mapping):
        return False
    refresh_ref = _path_text(authorization.get("refresh_credential_ref"))
    return (
        _clean_url(github.get("api_url")) == _clean_url(machine_github.get("api_url"))
        and str(authorization_source.get("kind") or "") == "github_app"
        and bool(refresh_ref)
        and Path(refresh_ref).expanduser().is_file()
    )


def _project_checkout_reused(
    cfg_path: Path,
    checkout: Any,
    project_id: int | None,
) -> bool:
    if project_id is None or not checkout:
        return False
    root = Path(str(checkout)).expanduser()
    if not root.is_dir():
        return False
    return _looks_like_git_checkout(root) and (
        machine_config.project_id(root, cfg_path) == project_id
    )


def _project_scaffold_installed(checkout: Any, project_id: int | None) -> bool:
    if project_id is None or not checkout:
        return False
    root = Path(str(checkout)).expanduser()
    try:
        manifest = project_install_files.load_manifest(root)
    except project_install_files.ProjectInstallError:
        return False
    if not isinstance(manifest, Mapping):
        return False
    return _positive_int(manifest.get("project_id")) == project_id


def _project_clone_checkout_reused(checkout: Any, remote_url: str, mode: str) -> bool:
    if mode not in onboard_project.PROJECT_REMOTE_MODES or not checkout or not remote_url:
        return False
    try:
        root = Path(str(checkout)).expanduser()
        return project_clone_resume.existing_clone_matches(root, remote_url)
    except Exception:
        return False


def _looks_like_git_checkout(root: Path) -> bool:
    return (root / ".git").exists()


def _positive_int(value: Any) -> int | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _clean_url(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def _path_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return str(Path(value).expanduser())


def _effective_path(value: str | Path) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return Path(value).expanduser()


__all__ = ["detect"]
