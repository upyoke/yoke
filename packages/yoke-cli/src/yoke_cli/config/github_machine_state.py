"""Configuration and report state for local GitHub App authorization."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Mapping

from yoke_cli.config import github_credentials
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import machine_config, secrets, writer
from yoke_contracts import github_app_installation_permissions as permission_contract
from yoke_contracts import github_origin
from yoke_contracts.machine_config import schema as contract

CLIENT_ID_ENV = "YOKE_GITHUB_APP_CLIENT_ID"
APP_SLUG_ENV = "YOKE_GITHUB_APP_SLUG"
APP_ID_ENV = "YOKE_GITHUB_APP_ID"
API_URL_ENV = "YOKE_GITHUB_APP_API_URL"
WEB_URL_ENV = "YOKE_GITHUB_WEB_URL"
_OWNED_CREDENTIAL_NAME = re.compile(
    r"github-app-user-[0-9a-f]{32}\.json"
)


def connected_report(
    *, config_path: str | Path | None, github: Mapping[str, Any],
    progress: list[dict[str, Any]], checked: bool,
    discovery_error: Exception | None = None, token_error: str | None = None,
) -> dict[str, Any]:
    validation = _public_validation_issues(
        contract.validate_github_config({"github": github})
    )
    raw_authorization = github.get("authorization")
    authorization = (
        dict(raw_authorization) if isinstance(raw_authorization, Mapping) else {}
    )
    auth_report = github_credentials.authorization_status(authorization)
    issues = [*validation, *auth_report.pop("issues")]
    if token_error:
        issues.append(reports.issue(
            "error", "github_user_token_unavailable", token_error,
            "Run `yoke github connect` to authorize again.",
        ))
    if discovery_error:
        issues.append(reports.issue(
            "error", "github_live_check_failed", str(discovery_error),
            "Retry `yoke github status`; reconnect if authorization was revoked.",
        ))
    installations = _mapping_list(github.get("installations"))
    permissions = _permission_report(installations)
    if not discovery_error and not token_error and not installations:
        issues.append(reports.issue(
            "warning", "github_app_installation_required",
            "GitHub user authorization succeeded, but the App has no installation access.",
            "Install the App, choose repositories, then run `yoke github status`.",
        ))
    for item in permissions["items"]:
        account = str(item.get("account_login") or "the account")
        if item["suspended"]:
            issues.append(reports.issue(
                "warning", "github_app_installation_suspended",
                f"The GitHub App installation for {account} is suspended.",
                "Restore or reinstall it, then run `yoke github status`.",
            ))
        if item["evaluation"]["ok"] is False:
            issues.append(reports.issue(
                "warning", "github_app_installation_permissions_incomplete",
                f"The GitHub App installation for {account} lacks required permissions.",
                "Approve the App permission changes, then run `yoke github status`.",
            ))
    if installations and permissions["usable"] is False:
        issues.append(reports.issue(
            "error", "github_app_no_usable_installation",
            "No GitHub App installation is active with all required permissions.",
            "Repair or add an App installation, then run `yoke github status`.",
        ))
    live_check_ok = None if not checked else not (discovery_error or token_error)
    report = reports.connected(
        config_path, github, authorization=auth_report, checked=checked,
        live_check_ok=live_check_ok, permissions=permissions, issues=issues,
    )
    try:
        endpoint_pair = github_origin.validate_github_endpoint_pair(
            str(report["api_url"]), str(report["web_url"]),
        )
    except github_origin.GitHubApiOriginError:
        # The validation issue above is the actionable result for stale config.
        # Do not synthesize an installation URL for an untrusted endpoint pair.
        pass
    else:
        try:
            report["install_url"] = endpoint_pair.app_install_url(
                str(report["app"]["slug"]),
            )
        except github_origin.GitHubApiOriginError:
            report.pop("install_url", None)
        if (
            report.get("ok") and not installations
            and not discovery_error and not token_error
        ):
            install_url = report.get("install_url")
            if install_url:
                report["next_action"] = {
                    "code": "install_github_app",
                    "message": "Install the GitHub App and choose repositories.",
                    "url": install_url,
                }
    report["progress"] = progress
    return report


def public_app_metadata(
    existing: Mapping[str, Any], *, client_id: str | None, app_slug: str | None,
    app_id: int | None, api_url: str | None, web_url: str | None,
) -> dict[str, Any]:
    selected_client = _setting(client_id, existing, "client_id", CLIENT_ID_ENV)
    selected_slug = _setting(app_slug, existing, "app_slug", APP_SLUG_ENV)
    if not re.fullmatch(r"[A-Za-z0-9-]+", selected_slug):
        raise ValueError("GitHub App slug may contain only letters, numbers, and hyphens")
    try:
        pair = github_origin.validate_github_endpoint_pair(
            _setting(api_url, existing, "api_url", API_URL_ENV,
                     default=contract.DEFAULT_GITHUB_API_URL),
            _setting(web_url, existing, "web_url", WEB_URL_ENV,
                     default=contract.DEFAULT_GITHUB_WEB_URL),
        )
        selected_api = pair.api.base_url
        selected_web = pair.web.base_url
    except github_origin.GitHubApiOriginError as exc:
        raise ValueError(str(exc)) from exc
    raw_app_id: Any = (
        app_id if app_id is not None
        else existing.get("app_id") or os.environ.get(APP_ID_ENV)
    )
    metadata: dict[str, Any] = {
        "api_url": selected_api, "web_url": selected_web,
        "app_slug": selected_slug, "client_id": selected_client,
    }
    if raw_app_id not in (None, ""):
        if isinstance(raw_app_id, bool):
            raise ValueError("GitHub App id must be a positive integer")
        try:
            parsed_app_id = int(raw_app_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("GitHub App id must be an integer") from exc
        if parsed_app_id <= 0:
            raise ValueError("GitHub App id must be positive")
        metadata["app_id"] = parsed_app_id
    return metadata


def github_entry(
    metadata: Mapping[str, Any], authorization: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    *,
    cached_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = dict(metadata)
    entry["authorization"] = dict(authorization)
    if snapshot is not None:
        entry.update({
            "installations": _mapping_list(snapshot.get("installations")),
            "repositories": _mapping_list(snapshot.get("repositories")),
        })
    elif cached_snapshot is not None:
        entry.update({
            "installations": _mapping_list(cached_snapshot.get("installations")),
            "repositories": _mapping_list(cached_snapshot.get("repositories")),
        })
    return entry


def existing_config(path: str | Path | None) -> dict[str, Any]:
    return machine_config.github_config(path)


def credential_ref(github: Mapping[str, Any]) -> str:
    authorization = github.get("authorization")
    if not isinstance(authorization, Mapping):
        return ""
    return str(authorization.get("refresh_credential_ref") or "").strip()


def mark_revoked(
    github: dict[str, Any], *, config_path: str | Path | None,
) -> str | None:
    expected_credential_ref = credential_ref(github)
    raw_authorization = github.get("authorization")
    authorization = (
        dict(raw_authorization) if isinstance(raw_authorization, Mapping) else {}
    )
    authorization["status"] = "revoked"
    github["authorization"] = authorization
    try:
        writer.set_github(
            github, expected_credential_ref=expected_credential_ref,
            path=config_path,
        )
    except writer.MachineConfigWriteError:
        return "Revoked authorization could not be persisted to machine config"
    return None


def remove_owned_credential(path: Path) -> bool:
    selected = path.expanduser()
    allowed = secrets.secrets_dir().resolve()
    resolved = selected.resolve(strict=False)
    if (
        not selected.is_absolute()
        or selected.parent.resolve(strict=False) != allowed
        or resolved.parent != allowed
        or not _OWNED_CREDENTIAL_NAME.fullmatch(selected.name)
    ):
        raise ValueError(
            "refusing to remove a file that is not a Yoke-owned GitHub App "
            "user credential"
        )
    try:
        return github_git_credential_file.delete_json_document(selected)
    except github_git_credential_file.CredentialFileError as exc:
        raise ValueError(str(exc)) from exc


def _permission_report(installations: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for installation in installations:
        raw_permissions = installation.get("permissions")
        evaluation = permission_contract.evaluate_installation_repository_permissions(
            raw_permissions if isinstance(raw_permissions, Mapping) else {}
        )
        items.append({
            "installation_id": installation.get("installation_id"),
            "account_login": installation.get("account_login"),
            "suspended": bool(installation.get("suspended")),
            "evaluation": evaluation,
        })
    return {
        "ok": None if not items else all(
            item["evaluation"]["ok"] for item in items
        ),
        "usable": None if not items else any(
            item["evaluation"]["ok"] and not item["suspended"] for item in items
        ),
        "mode": "github_app_installation",
        "items": items,
    }


def _public_validation_issues(values: list[Any]) -> list[dict[str, Any]]:
    issues = []
    for value in values:
        item = value.as_dict()
        if item.get("code") == "github_authorization_kind_invalid":
            item = reports.issue(
                "error", "github_authorization_invalid",
                "GitHub App authorization has an unsupported format",
                "Reconnect GitHub through the Yoke GitHub App.",
            )
        issues.append(item)
    return issues


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _setting(
    explicit: str | None, existing: Mapping[str, Any], key: str, env: str,
    *, default: str = "",
) -> str:
    if explicit is not None and explicit != "":
        raw: Any = explicit
    elif key in existing and existing.get(key) not in (None, ""):
        raw = existing.get(key)
    else:
        raw = os.environ.get(env) or default
    if not isinstance(raw, str):
        raise ValueError(
            f"GitHub App {key.replace('_', ' ')} must be a string"
        )
    value = raw.strip()
    if not value:
        raise ValueError(
            f"GitHub App {key.replace('_', ' ')} is required (--{key.replace('_', '-')})"
        )
    return value
