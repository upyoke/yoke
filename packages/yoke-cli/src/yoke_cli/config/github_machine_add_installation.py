"""Add-installation flow that reuses an existing machine user authorization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_machine_access
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_user_tokens, writer


def add_installation(
    *,
    config_path: str | Path | None,
    github: Mapping[str, Any],
    metadata: Mapping[str, Any],
    profile_opener: Callable[..., Any] | None,
    token_opener: Callable[..., Any] | None,
    api_opener: Callable[..., Any] | None,
    browser_open: Callable[[str], Any] | None,
    notify: Callable[[Mapping[str, Any]], None] | None,
    sleep: Callable[[float], None],
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Open install settings and rediscover without another device flow."""

    expected_ref = state.credential_ref(github)
    if not expected_ref:
        raise error_type(
            "saved GitHub authorization has no reusable credential; reconnect"
        )
    try:
        token = github_user_tokens.access_token_from_machine_config(
            config_path=config_path,
            opener=token_opener,
            profile_opener=profile_opener,
            _profile_proven=True,
            _expected_service_api_url=(
                str(metadata.get("profile_service_api_url") or "") or None
            ),
            _expected_local_connection=(
                metadata.get("profile_source")
                in {
                    github_app_public_profile.PROFILE_SOURCE_LOCAL_EXPLICIT,
                    github_app_public_profile.PROFILE_SOURCE_LOCAL_PRODUCT,
                }
            ),
        )
    except github_user_tokens.GitHubUserTokenError as exc:
        raise error_type(
            "saved GitHub authorization could not be refreshed; reconnect"
        ) from exc
    opening_report = state.connected_report(
        config_path=config_path,
        github=github,
        progress=[],
        checked=False,
    )
    github_machine_access.open_install_page(
        opening_report,
        browser_open=browser_open,
        notify=notify,
        pending=False,
        error_type=error_type,
    )
    try:
        snapshot = github_machine_access.discover_access_with_unauthorized_retry(
            api_url=str(metadata["api_url"]),
            access_token=token.access_token,
            opener=api_opener,
            sleep=sleep,
            notify=notify,
            web_url=str(metadata["web_url"]),
            expected_app_id=int(metadata["app_id"]),
            expected_app_slug=str(metadata["app_slug"]),
        )
    except github_app_user_api.GitHubAppUserApiError as exc:
        raise error_type(
            "GitHub App installation access could not be refreshed; the saved "
            "authorization was preserved"
        ) from exc
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
            refreshed,
            expected_credential_ref=expected_ref,
            expected_profile_identity=state.profile_identity(github),
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise error_type(str(exc)) from exc
    report = state.connected_report(
        config_path=config_path,
        github=refreshed,
        progress=[],
        checked=True,
    )
    report.update({
        "operation": "github.connect",
        "authorization_reused": True,
        "install_url": opening_report["install_url"],
        "install_browser_opened": opening_report["install_browser_opened"],
    })
    return report


__all__ = ["add_installation"]
