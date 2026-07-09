"""Machine-level GitHub App connection checks for the product CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_credentials
from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract


class GitHubMachineError(RuntimeError):
    """The machine GitHub App connection cannot be used."""


def connect(
    *,
    config_path: str | Path | None,
    token: str | None = None,
    token_file: str | Path | None = None,
    token_source_kind: str = "argument",
    api_url: str | None,
    github_repo: str | None = None,
) -> dict[str, Any]:
    selected_url = _clean_api_url(api_url)
    report = _base_report(config_path, selected_url)
    report.update({
        "ok": False,
        "operation": "github.connect",
        "configured": False,
        "applied": False,
        "connection_model": "github_app",
        "token_source": {"kind": token_source_kind if token or token_file else "none"},
        "identity": {"checked": False, "ok": None},
        "access": _empty_access(),
        "scopes": [],
        "permissions": {"ok": None, "mode": "github_app"},
        "issues": [_issue(
            "error",
            "github_app_browser_flow_unavailable",
            (
                "GitHub App browser authorization is the only supported "
                "machine GitHub connection, and the browser callback flow is "
                "not available in this build."
            ),
            (
                "Use backlog-only for now, then run `yoke github connect` when "
                "browser authorization is available."
            ),
        )],
    })
    if token or token_file or github_repo:
        report["issues"].insert(0, _issue(
            "error",
            "github_manual_credential_input_unsupported",
            "yoke github connect no longer accepts manual GitHub credentials or repo probes.",
            "Run `yoke github connect` with no token flags to start the GitHub App flow.",
        ))
    return report


def status(
    *,
    config_path: str | Path | None,
    api_url: str | None = None,
    check: bool = True,
    github_repo: str | None = None,
) -> dict[str, Any]:
    report = _base_report(config_path, api_url)
    report["operation"] = "github.status"
    try:
        cfg = machine_config.github_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise GitHubMachineError(str(exc)) from exc
    if not cfg:
        report.update({
            "ok": False,
            "configured": False,
            "connection_model": "github_app",
            "identity": {"checked": False, "ok": None},
            "access": _empty_access(),
            "scopes": [],
            "permissions": {"ok": None, "mode": "github_app"},
            "issues": [_issue(
                "error",
                "github_not_configured",
                "machine GitHub App authorization is not configured",
                "Run `yoke github connect` to open the GitHub App flow.",
            )],
        })
        return report
    selected_url = _clean_api_url(api_url or str(cfg.get("api_url") or ""))
    report["api_url"] = selected_url
    validation_issues = [
        issue.as_dict()
        for issue in contract.validate_github_config({"github": cfg})
    ]
    authorization = cfg.get("authorization")
    authorization = authorization if isinstance(authorization, Mapping) else {}
    authorization_report = github_credentials.authorization_status(authorization)
    issues = [*validation_issues, *authorization_report.pop("issues")]
    scopes = list(authorization.get("scopes") or [])
    permissions = authorization.get("permissions")
    permissions = permissions if isinstance(permissions, Mapping) else {}
    report.update({
        "ok": not any(issue.get("severity") == "error" for issue in issues),
        "configured": True,
        "connection_model": "github_app",
        "app": {
            "slug": str(cfg.get("app_slug") or ""),
            "app_id": cfg.get("app_id"),
            "client_id": str(cfg.get("client_id") or ""),
        },
        "authorization": authorization_report,
        "credential_source": {"kind": None, "present": None},
        "identity": _offline_identity(authorization, check=check),
        "access": _app_access(cfg),
        "scopes": scopes,
        "permissions": {
            "ok": None if not permissions else True,
            "mode": "github_app",
            "summary": _permission_summary(permissions),
            "items": dict(permissions),
        },
        "issues": issues,
    })
    return report


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_human(report: Mapping[str, Any]) -> str:
    lines = [
        "Yoke GitHub",
        f"  config: {report.get('config_path')}",
        f"  api_url: {report.get('api_url')}",
        f"  configured: {str(report.get('configured')).lower()}",
        f"  ok: {str(report.get('ok')).lower()}",
    ]
    identity = report.get("identity")
    if isinstance(identity, Mapping) and identity.get("checked"):
        lines.append(f"  login: {identity.get('login')}")
    access = report.get("access")
    if isinstance(access, Mapping):
        lines.append(f"  owners: {', '.join(access.get('owners') or [])}")
        repos = access.get("repos") or []
        lines.append(f"  repos: {len(repos)} accessible")
        requested_repo = access.get("requested_repo")
        if isinstance(requested_repo, Mapping):
            lines.append(
                "  requested_repo: "
                f"{requested_repo.get('full_name')} "
                f"ok={str(requested_repo.get('ok')).lower()}"
            )
    permissions = report.get("permissions")
    if isinstance(permissions, Mapping) and permissions.get("ok") is not None:
        lines.append(
            "  permissions: "
            f"{str(permissions.get('ok')).lower()} "
            f"({permissions.get('mode')})"
        )
        if permissions.get("summary"):
            lines.append(f"  permission_summary: {permissions.get('summary')}")
    issues = report.get("issues") or []
    if issues:
        lines.append("")
        lines.append("Issues:")
        for issue in issues:
            lines.append(f"  - {issue.get('code')}: {issue.get('message')}")
    lines.append("")
    return "\n".join(lines)


def _base_report(
    config_path: str | Path | None,
    api_url: str | None,
) -> dict[str, Any]:
    cfg_path = machine_config.config_path(config_path)
    return {
        "config_path": str(cfg_path),
        "api_url": _clean_api_url(api_url),
        "connection_model": "github_app",
        "authorization": {
            "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
            "present": None,
        },
    }


def _offline_identity(authorization: Mapping[str, Any], *, check: bool) -> dict[str, Any]:
    return {
        "checked": check,
        "ok": None,
        "login": authorization.get("login") or "",
        "id": authorization.get("github_user_id"),
    }


def _empty_access() -> dict[str, Any]:
    return {
        "owners": [],
        "repos": [],
        "repo_count": 0,
        "repo_listing_ok": None,
        "org_listing_ok": None,
    }


def _app_access(cfg: Mapping[str, Any]) -> dict[str, Any]:
    installations = [
        item for item in cfg.get("installations") or []
        if isinstance(item, Mapping)
    ]
    repositories = [
        item for item in cfg.get("repositories") or []
        if isinstance(item, Mapping)
    ]
    owners = [
        str(item.get("account_login"))
        for item in installations
        if str(item.get("account_login") or "")
    ]
    repos = [
        str(item.get("full_name"))
        for item in repositories
        if str(item.get("full_name") or "")
    ]
    return {
        "owners": owners,
        "repos": repos,
        "repo_count": len(repos),
        "repo_listing_ok": None,
        "org_listing_ok": None,
        "installations": [dict(item) for item in installations],
    }


def _permission_summary(permissions: Mapping[str, Any]) -> str:
    if not permissions:
        return ""
    enabled = [
        f"{key}:{value}"
        for key, value in sorted(permissions.items())
        if value not in (None, "", False)
    ]
    return ", ".join(enabled)


def _clean_api_url(api_url: str | None) -> str:
    value = (api_url or contract.DEFAULT_GITHUB_API_URL).strip().rstrip("/")
    if not value:
        return contract.DEFAULT_GITHUB_API_URL
    return value


def _issue(severity: str, code: str, message: str, hint: str = "") -> dict[str, str]:
    issue = {"severity": severity, "code": code, "message": message}
    if hint:
        issue["hint"] = hint
    return issue


__all__ = [
    "GitHubMachineError",
    "connect",
    "dumps_json",
    "render_human",
    "status",
]
