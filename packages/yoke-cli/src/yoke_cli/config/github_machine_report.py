"""Stable human and JSON report shapes for local GitHub App commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract
from yoke_contracts.machine_config.schema_github_access import (
    GITHUB_REPOSITORY_ALLOWED_KEYS,
)


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
            "Run `yoke github connect --client-id … --app-slug …`.",
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
    repositories = [
        {
            key: value
            for key, value in item.items()
            if key in GITHUB_REPOSITORY_ALLOWED_KEYS
        }
        for item in github.get("repositories") or []
        if isinstance(item, Mapping)
    ]
    ok = not any(item.get("severity") == "error" for item in issues)
    return {
        **_base(config_path, str(github.get("api_url") or "")),
        "web_url": str(github.get("web_url") or contract.DEFAULT_GITHUB_WEB_URL),
        "ok": ok,
        "ready": bool(ok and installations and permissions.get("usable") is True),
        "operation": "github.status",
        "configured": True,
        "state": "connected" if installations else "pending_installation",
        "app": {
            "slug": str(github.get("app_slug") or ""),
            "app_id": github.get("app_id"),
            "client_id": str(github.get("client_id") or ""),
        },
        "authorization": dict(authorization),
        "identity": {
            "checked": checked,
            "ok": live_check_ok,
            "snapshot_source": "live" if live_check_ok is True else "cached",
            "login": str(auth.get("login") or ""),
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
        lines.append(f"  owners: {', '.join(access.get('owners') or [])}")
        lines.append(f"  repos: {len(access.get('repos') or [])} accessible")
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
    progress = report.get("progress") or []
    for event in progress:
        if event.get("phase") == "device_authorization":
            lines.extend([
                f"  verification_url: {event.get('verification_uri')}",
                f"  user_code: {event.get('user_code')}",
            ])
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
