"""Stable human and JSON report shapes for local GitHub App commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_contracts import github_app_snapshot
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config.schema_github_access import (
    GITHUB_REPOSITORY_ALLOWED_KEYS,
)

_HUMAN_LIST_LIMIT = 20


def not_configured(
    config_path: str | Path | None, api_url: str | None,
) -> dict[str, Any]:
    return {
        **_base(config_path, api_url),
        "ok": False,
        "ready": False,
        "operation": "github.status",
        "configured": False,
        "identity": {"checked": False, "ok": None},
        "access": _empty_access(),
        "permissions": {
            "ok": None, "usable": None, "mode": "github_app_installation",
        },
        "issues": [issue(
            "error", "github_not_configured",
            "machine GitHub App authorization is not configured",
            "Run `yoke github connect` against the active Yoke service.",
        )],
    }


def connected(
    config_path: str | Path | None,
    github: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    checked: bool,
    live_check_ok: bool | None,
    permissions: Mapping[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    auth = github.get("authorization")
    auth = auth if isinstance(auth, Mapping) else {}
    installations = [
        dict(item) for item in github.get("installations") or []
        if isinstance(item, Mapping)
    ]
    repositories = []
    for item in github.get("repositories") or []:
        if not isinstance(item, Mapping):
            continue
        try:
            full_name = github_app_snapshot.repository_full_name(
                item.get("full_name"),
            )
            branch = github_app_snapshot.default_branch(
                item.get("default_branch"),
            )
        except github_app_snapshot.GitHubAppSnapshotError:
            continue
        normalized = {
            key: value for key, value in item.items()
            if key in GITHUB_REPOSITORY_ALLOWED_KEYS
        }
        normalized["full_name"] = full_name
        normalized["default_branch"] = branch
        if isinstance(item.get("private"), bool):
            normalized["private"] = item["private"]
        repositories.append(normalized)
    ok = not any(item.get("severity") == "error" for item in issues)
    try:
        login = github_app_snapshot.user_login(auth.get("login"))
    except github_app_snapshot.GitHubAppSnapshotError:
        login = ""
    try:
        app_slug = github_app_snapshot.app_slug(
            github.get("app_slug"), "github.app_slug",
        )
    except github_app_snapshot.GitHubAppSnapshotError:
        app_slug = ""
    return {
        **_base(config_path, str(github.get("api_url") or "")),
        "web_url": str(github.get("web_url") or contract.DEFAULT_GITHUB_WEB_URL),
        "ok": ok,
        "ready": bool(ok and installations and permissions.get("usable") is True),
        "operation": "github.status",
        "configured": True,
        "state": "connected" if installations else "pending_installation",
        "app": {
            "slug": app_slug,
            "app_id": github.get("app_id"),
            "client_id": str(github.get("client_id") or ""),
        },
        "authorization": dict(authorization),
        "identity": {
            "checked": checked,
            "ok": live_check_ok,
            "snapshot_source": "live" if live_check_ok is True else "cached",
            "login": login,
            "id": auth.get("github_user_id"),
        },
        "access": {
            "owners": [str(item.get("account_login")) for item in installations],
            "repos": [str(item.get("full_name")) for item in repositories],
            "repositories": repositories,
            "repo_count": len(repositories),
            "repo_listing_ok": live_check_ok,
            "org_listing_ok": live_check_ok,
            "snapshot_source": "live" if live_check_ok is True else "cached",
            "installations": installations,
        },
        "permissions": dict(permissions),
        "issues": issues,
    }


def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "Yoke GitHub",
        f"  config: {report.get('config_path')}",
        f"  api_url: {report.get('api_url')}",
        f"  configured: {str(report.get('configured')).lower()}",
        f"  ok: {str(report.get('ok')).lower()}",
        f"  ready: {str(report.get('ready')).lower()}",
    ]
    identity = report.get("identity")
    if isinstance(identity, Mapping) and identity.get("login"):
        lines.append(f"  login: {identity.get('login')}")
    access = report.get("access")
    if isinstance(access, Mapping):
        lines.append(f"  access_snapshot: {access.get('snapshot_source')}")
        installations = [
            item for item in access.get("installations") or []
            if isinstance(item, Mapping)
        ]
        if installations:
            lines.append("  installations:")
            for item in installations[:_HUMAN_LIST_LIMIT]:
                state = "suspended" if item.get("suspended") else "active"
                lines.append(
                    "    - "
                    f"{item.get('account_login') or '<unknown>'} "
                    f"({item.get('account_type') or 'account'}, {state}, "
                    f"{item.get('repository_selection') or 'selected'} repos)"
                )
            _append_omitted(lines, len(installations), "installations")
        else:
            lines.append(
                "  installations: none (installation or organization approval pending)"
            )
        repos = [str(item) for item in access.get("repos") or []]
        lines.append(f"  repositories: {len(repos)} accessible")
        for repo in repos[:_HUMAN_LIST_LIMIT]:
            lines.append(f"    - {repo}")
        _append_omitted(lines, len(repos), "repositories")
    permissions = report.get("permissions")
    if isinstance(permissions, Mapping) and permissions.get("ok") is not None:
        lines.append(f"  permissions: {str(permissions.get('ok')).lower()}")
        for item in permissions.get("items") or []:
            evaluation = item.get("evaluation") if isinstance(item, Mapping) else None
            missing = evaluation.get("missing") if isinstance(evaluation, Mapping) else []
            for permission in missing or []:
                lines.append(
                    "  missing_permission: "
                    f"{item.get('account_login')} "
                    f"{permission.get('key')}:{permission.get('required')} "
                    f"(granted={permission.get('granted') or 'none'})"
                )
            if item.get("settings_url") and (
                item.get("suspended") or missing
            ):
                lines.append(f"  repair_url: {item.get('settings_url')}")
    progress = report.get("progress") or []
    for event in progress:
        if event.get("phase") == "device_authorization":
            lines.append(
                f"  verification_url: {event.get('verification_uri')}"
            )
    if report.get("install_url"):
        lines.append(f"  install_url: {report.get('install_url')}")
    if report.get("issues"):
        lines.append("")
        lines.append("Issues:")
        for item in report["issues"]:
            lines.append(f"  - {item.get('code')}: {item.get('message')}")
            if item.get("hint"):
                lines.append(f"    hint: {item.get('hint')}")
    lines.append("")
    return "\n".join(lines)


def _append_omitted(lines: list[str], total: int, label: str) -> None:
    omitted = total - _HUMAN_LIST_LIMIT
    if omitted > 0:
        lines.append(f"    ... {omitted} more {label}")


def issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if hint:
        item["hint"] = hint
    return item


def _base(config_path: str | Path | None, api_url: str | None) -> dict[str, Any]:
    return {
        "config_path": str(machine_config.config_path(config_path)),
        "api_url": str(api_url or contract.DEFAULT_GITHUB_API_URL).rstrip("/"),
        "connection_model": "github_app",
    }


def _empty_access() -> dict[str, Any]:
    return {"owners": [], "repos": [], "repositories": [], "repo_count": 0,
            "repo_listing_ok": None, "org_listing_ok": None}


__all__ = ["connected", "issue", "not_configured", "render_human"]
