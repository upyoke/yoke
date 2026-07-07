"""Machine-level GitHub credential checks for the product CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_credentials
from yoke_cli.config.github_machine_verify import (
    GitHubMachineVerificationError,
    verify as _verify,
)
from yoke_cli.config.github_storage import (
    GitHubCredentialStorageError,
    store_credential_source as _store_credential_source,
)
from yoke_cli.config import machine_config
from yoke_cli.config import writer
from yoke_contracts.machine_config import schema as contract

class GitHubMachineError(RuntimeError):
    """The machine GitHub credential cannot be used."""


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
    secret, source = _resolve_token_source(
        token=token,
        token_file=token_file,
        source_kind=token_source_kind,
    )
    try:
        verification = _verify(selected_url, secret, github_repo=github_repo)
    except GitHubMachineVerificationError as exc:
        raise GitHubMachineError(str(exc)) from exc
    try:
        credential_source = _store_credential_source(secret)
        writer.set_github(
            credential_source=credential_source,
            api_url=selected_url,
            verified_login=verification["identity"].get("login"),
            verified_user_id=verification["identity"].get("id"),
            scopes=verification["scopes"],
            path=config_path,
        )
    except (
        GitHubCredentialStorageError,
        writer.MachineConfigWriteError,
        machine_config.MachineConfigError,
    ) as exc:
        raise GitHubMachineError(str(exc)) from exc
    report = _base_report(config_path, selected_url)
    report.update({
        "ok": True,
        "operation": "github.connect",
        "configured": True,
        "applied": True,
        "token_source": source,
        "identity": verification["identity"],
        "access": verification["access"],
        "scopes": verification["scopes"],
        "permissions": verification.get("permissions", {"ok": None, "mode": "unknown"}),
    })
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
            "identity": {"checked": False, "ok": None},
            "access": _empty_access(),
            "scopes": [],
            "permissions": {"ok": None, "mode": "unknown"},
            "issues": [_issue(
                "error",
                "github_not_configured",
                "machine GitHub credentials are not configured",
                "Run `yoke github connect TOKEN`.",
            )],
        })
        return report
    source = cfg.get("credential_source")
    source = source if isinstance(source, Mapping) else {}
    selected_url = _clean_api_url(api_url or str(cfg.get("api_url") or ""))
    report["api_url"] = selected_url
    credential = github_credentials.credential_status(source)
    report["credential_source"] = credential
    issues = list(credential.pop("issues"))
    if issues or not check:
        report.update({
            "ok": not issues,
            "configured": True,
            "identity": _offline_identity(cfg, check=check),
            "access": _empty_access(),
            "scopes": list(cfg.get("scopes") or []),
            "permissions": {"ok": None, "mode": "offline"},
            "issues": issues,
        })
        return report
    try:
        token = github_credentials.read_token_source(source)
    except github_credentials.GitHubCredentialError as exc:
        raise GitHubMachineError(str(exc)) from exc
    try:
        verification = _verify(selected_url, token, github_repo=github_repo)
    except GitHubMachineVerificationError as exc:
        raise GitHubMachineError(str(exc)) from exc
    report.update({
        "ok": True,
        "configured": True,
        "identity": verification["identity"],
        "access": verification["access"],
        "scopes": verification["scopes"],
        "permissions": verification.get("permissions", {"ok": None, "mode": "unknown"}),
        "issues": [],
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
        "credential_source": {
            "kind": contract.CREDENTIAL_KIND_TOKEN_FILE,
            "present": None,
        },
    }


def _offline_identity(cfg: Mapping[str, Any], *, check: bool) -> dict[str, Any]:
    return {
        "checked": check,
        "ok": None,
        "login": cfg.get("verified_login") or "",
        "id": cfg.get("verified_user_id"),
    }


def _empty_access() -> dict[str, Any]:
    return {
        "owners": [],
        "repos": [],
        "repo_count": 0,
        "repo_listing_ok": None,
        "org_listing_ok": None,
    }


def _resolve_token_source(
    *,
    token: str | None,
    token_file: str | Path | None,
    source_kind: str,
) -> tuple[str, dict[str, str]]:
    if token_file is not None:
        token_path = Path(token_file).expanduser()
        return _read_token(token_path), {
            "kind": "token_file",
            "path": str(token_path),
        }
    secret = (token or "").strip()
    if not secret:
        raise GitHubMachineError("GitHub token is empty")
    return secret, {"kind": source_kind}


def _read_token(token_path: Path) -> str:
    try:
        return github_credentials.read_token_file(token_path)
    except github_credentials.GitHubCredentialError as exc:
        raise GitHubMachineError(str(exc)) from exc


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
