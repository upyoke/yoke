"""Configuration and report state for local GitHub App authorization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_credentials
from yoke_cli.config.github_machine_credential_lifecycle import (
    cleanup_quarantined_credentials as cleanup_quarantined_credentials,
    is_owned_credential_path as is_owned_credential_path,
    quarantine_owned_credential as quarantine_owned_credential,
    release_config_credential as release_config_credential,
    remove_owned_credential as remove_owned_credential,
    remove_quarantined_credential as remove_quarantined_credential,
    restore_quarantined_credential as restore_quarantined_credential,
)
from yoke_cli.config import github_machine_installations
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import machine_config, writer
from yoke_contracts import github_app_tokens, github_origin
from yoke_contracts.machine_config import schema as contract

CLIENT_ID_ENV = github_app_public_profile.CLIENT_ID_ENV
APP_SLUG_ENV = github_app_public_profile.APP_SLUG_ENV
APP_ID_ENV = github_app_public_profile.APP_ID_ENV
API_URL_ENV = github_app_public_profile.API_URL_ENV
WEB_URL_ENV = github_app_public_profile.WEB_URL_ENV


def connected_report(
    *,
    config_path: str | Path | None,
    github: Mapping[str, Any],
    progress: list[dict[str, Any]],
    checked: bool,
    discovery_error: Exception | None = None,
    token_error: str | None = None,
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
        issues.append(
            reports.issue(
                "error",
                "github_user_token_unavailable",
                token_error,
                "Run `yoke github connect` to authorize again.",
            )
        )
    if discovery_error:
        issues.append(
            reports.issue(
                "error",
                "github_live_check_failed",
                str(discovery_error),
                "Retry `yoke github status`; reconnect if authorization was revoked.",
            )
        )
    installations = github_machine_installations.safe_installations(github)
    cached_identity_mismatch = github_machine_installations.identity_mismatch(
        github,
        installations,
    )
    report_github = dict(github)
    report_github["installations"] = installations
    if cached_identity_mismatch:
        report_github["repositories"] = []
        issues.append(
            reports.issue(
                "error",
                "github_cached_installation_app_mismatch",
                "Cached GitHub installation access belongs to a different App profile.",
                "Run `yoke github status --check`; reconnect if the mismatch remains.",
            )
        )
    permissions = github_machine_installations.permission_report(installations)
    if not discovery_error and not token_error and not installations:
        issues.append(
            reports.issue(
                "warning",
                "github_app_installation_required",
                "GitHub user authorization succeeded, but the App has no installation access.",
                "Install the App, choose repositories, then run `yoke github status`.",
            )
        )
    for item in permissions["items"]:
        account = str(item.get("account_login") or "the account")
        if item["suspended"]:
            issues.append(
                reports.issue(
                    "warning",
                    "github_app_installation_suspended",
                    f"The GitHub App installation for {account} is suspended.",
                    "Restore or reinstall it, then run `yoke github status`.",
                )
            )
        if item["evaluation"]["ok"] is False:
            issues.append(
                reports.issue(
                    "warning",
                    "github_app_installation_permissions_incomplete",
                    f"The GitHub App installation for {account} lacks required permissions.",
                    "Approve the App permission changes, then run `yoke github status`.",
                )
            )
    if installations and permissions["usable"] is False:
        issues.append(
            reports.issue(
                "error",
                "github_app_no_usable_installation",
                "No GitHub App installation is active with all required permissions.",
                "Repair or add an App installation, then run `yoke github status`.",
            )
        )
    live_check_ok = None if not checked else not (discovery_error or token_error)
    report = reports.connected(
        config_path,
        report_github,
        authorization=auth_report,
        checked=checked,
        live_check_ok=live_check_ok,
        permissions=permissions,
        issues=issues,
    )
    try:
        endpoint_pair = github_origin.validate_github_endpoint_pair(
            str(report["api_url"]),
            str(report["web_url"]),
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
            report.get("ok")
            and not installations
            and not discovery_error
            and not token_error
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
    *,
    service_api_url: str | None,
    client_id: str | None,
    app_slug: str | None,
    app_id: int | str | None,
    api_url: str | None,
    web_url: str | None,
    opener: Any | None = None,
) -> dict[str, Any]:
    profile = github_app_public_profile.resolve(
        service_api_url=service_api_url,
        client_id=client_id,
        app_slug=app_slug,
        app_id=app_id,
        api_url=api_url,
        web_url=web_url,
        opener=opener,
    )
    return github_app_public_profile.local_explicit_metadata(profile)


def github_entry(
    metadata: Mapping[str, Any],
    authorization: Mapping[str, Any],
    snapshot: Mapping[str, Any] | None,
    *,
    cached_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = dict(metadata)
    entry["authorization"] = dict(authorization)
    if snapshot is not None:
        entry.update(
            {
                "installations": _mapping_list(snapshot.get("installations")),
                "repositories": _mapping_list(snapshot.get("repositories")),
            }
        )
    elif cached_snapshot is not None:
        entry.update(
            {
                "installations": _mapping_list(cached_snapshot.get("installations")),
                "repositories": _mapping_list(cached_snapshot.get("repositories")),
            }
        )
    return entry


def existing_config(path: str | Path | None) -> dict[str, Any]:
    return machine_config.github_config(path)


def credential_ref(github: Mapping[str, Any]) -> str:
    authorization = github.get("authorization")
    if not isinstance(authorization, Mapping):
        return ""
    return str(authorization.get("refresh_credential_ref") or "").strip()


def profile_identity(github: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: github.get(field)
        for field in github_app_tokens.GITHUB_PROFILE_IDENTITY_FIELDS
    }


def mark_revoked(
    github: dict[str, Any],
    *,
    config_path: str | Path | None,
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
            github,
            expected_credential_ref=expected_credential_ref,
            expected_profile_identity=profile_identity(github),
            path=config_path,
        )
    except writer.MachineConfigWriteError:
        return "Revoked authorization could not be persisted to machine config"
    return None


def _public_validation_issues(values: list[Any]) -> list[dict[str, Any]]:
    issues = []
    for value in values:
        item = value.as_dict()
        if item.get("code") == "github_authorization_kind_invalid":
            item = reports.issue(
                "error",
                "github_authorization_invalid",
                "GitHub App authorization has an unsupported format",
                "Reconnect GitHub through the Yoke GitHub App.",
            )
        issues.append(item)
    return issues


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


_permission_report = github_machine_installations.permission_report
