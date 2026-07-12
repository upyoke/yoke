"""Live and offline status checks for machine GitHub authorization."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from pathlib import Path
import time
from typing import Any, Callable

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_machine_access
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import machine_config, writer


def status(
    *,
    config_path: str | Path | None,
    check: bool,
    api_opener: Callable[..., Any] | None,
    token_opener: Callable[..., Any] | None,
    service_api_url: str | None,
    local_connection_selected: bool,
    profile_opener: Callable[..., Any] | None,
    sleep: Callable[[float], None] | None,
    now: datetime | None,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Return local state or verify it against the selected service and GitHub."""

    try:
        github = state.existing_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise error_type(str(exc)) from exc
    if not github:
        return reports.not_configured(config_path, None)
    if not check:
        return state.connected_report(
            config_path=config_path, github=github, progress=[], checked=False,
        )
    try:
        github_app_public_profile.resolve_selected_and_match(
            github,
            config_path=config_path,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
            opener=profile_opener,
        )
    except github_app_public_profile.GitHubAppPublicProfileError as exc:
        raise error_type(str(exc)) from exc
    helper_refresh_failed = False
    try:
        github_git_credentials.refresh_installed_helper()
    except (OSError, github_git_credentials.GitHubCredentialBundleError):
        helper_refresh_failed = True
    expected_credential_ref = state.credential_ref(github)
    try:
        token = github_local_user_access.access_token(
            config_path=config_path, opener=token_opener,
            profile_opener=profile_opener, now=now,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
        if token.refresh_credential_ref != expected_credential_ref:
            raise error_type(
                "machine GitHub App authorization changed while status was "
                "running; retry against the current connection"
            )
        snapshot = github_machine_access.discover_access_with_unauthorized_retry(
            api_url=str(github["api_url"]), access_token=token.access_token,
            opener=api_opener,
            sleep=sleep or time.sleep,
            web_url=str(github["web_url"]),
            expected_app_id=int(github["app_id"]),
            expected_app_slug=str(github["app_slug"]),
        )
    except github_local_user_access.GitHubLocalUserAccessError:
        return _with_helper_issue(state.connected_report(
            config_path=config_path, github=github, progress=[], checked=True,
            token_error=(
                "GitHub App user authorization could not provide a valid access "
                "token"
            ),
        ), helper_refresh_failed)
    except github_app_user_api.GitHubAppUserApiError as exc:
        persistence_error = None
        if exc.status == HTTPStatus.UNAUTHORIZED:
            persistence_error = state.mark_revoked(github, config_path=config_path)
        report = state.connected_report(
            config_path=config_path, github=github, progress=[], checked=True,
            discovery_error=exc,
        )
        if persistence_error:
            report["issues"].append(reports.issue(
                "error", "github_revoked_status_not_persisted", persistence_error,
                "Repair machine-config permissions, then reconnect GitHub.",
            ))
        return _with_helper_issue(report, helper_refresh_failed)
    refreshed = dict(github)
    authorization = dict(refreshed.get("authorization") or {})
    authorization.update({
        "status": "authorized",
        "github_user_id": snapshot["user"]["id"],
        "login": snapshot["user"]["login"],
    })
    refreshed.update({
        "authorization": authorization,
        "installations": snapshot["installations"],
        "repositories": snapshot["repositories"],
    })
    try:
        writer.set_github(
            refreshed, expected_credential_ref=expected_credential_ref,
            expected_profile_identity=state.profile_identity(github),
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise error_type(str(exc)) from exc
    return _with_helper_issue(state.connected_report(
        config_path=config_path, github=refreshed, progress=[], checked=True,
    ), helper_refresh_failed)


def _with_helper_issue(
    report: dict[str, Any], helper_refresh_failed: bool,
) -> dict[str, Any]:
    """Compose helper repair independently from token and API status."""

    if helper_refresh_failed:
        report["issues"].append(reports.issue(
            "warning",
            "github_git_helper_upgrade_pending",
            "The installed GitHub credential helper could not be upgraded",
            "Repair the Python installation permissions, then rerun status.",
        ))
    return report


__all__ = ["status"]
