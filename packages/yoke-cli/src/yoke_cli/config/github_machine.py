"""Machine-level GitHub App authorization for the product CLI."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import uuid

from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_device_flow
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config, secrets, writer
from yoke_contracts.machine_config import schema as contract

class GitHubMachineError(RuntimeError):
    """The machine GitHub App connection cannot be used."""


def connect(
    *,
    config_path: str | Path | None,
    client_id: str | None = None,
    app_slug: str | None = None,
    app_id: int | None = None,
    api_url: str | None = None,
    web_url: str | None = None,
    add_installation: bool = False,
    device_opener: Callable[..., Any] | None = None,
    api_opener: Callable[..., Any] | None = None,
    browser_open: Callable[[str], Any] | None = None,
    notify: Callable[[Mapping[str, Any]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Authorize the App user, discover installations, and persist metadata."""
    try:
        existing = state.existing_config(config_path)
        metadata = state.public_app_metadata(
            existing, client_id=client_id, app_slug=app_slug, app_id=app_id,
            api_url=api_url, web_url=web_url,
        )
    except (ValueError, machine_config.MachineConfigError) as exc:
        raise GitHubMachineError(str(exc)) from exc
    progress: list[dict[str, Any]] = []

    def record(event: Mapping[str, Any]) -> None:
        public_event = dict(event)
        progress.append(public_event)
        if notify is not None:
            notify(public_event)

    device_kwargs: dict[str, Any] = {}
    if sleep is not None:
        device_kwargs["sleep"] = sleep
    if monotonic is not None:
        device_kwargs["monotonic"] = monotonic
    try:
        device = github_device_flow.authorize(
            client_id=metadata["client_id"], web_url=metadata["web_url"],
            opener=device_opener, browser_open=browser_open, notify=record,
            **device_kwargs,
        )
    except github_device_flow.GitHubDeviceFlowError as exc:
        raise GitHubMachineError(str(exc)) from exc
    expected_credential_ref = state.credential_ref(existing)
    credential_path = secrets.secret_path(
        f"github-app-user-{uuid.uuid4().hex}", "json"
    )
    try:
        github_user_tokens.store_initial_token(
            credential_path, device.token_response, now=now
        )
    except github_user_tokens.GitHubUserTokenError as exc:
        raise GitHubMachineError(
            "GitHub App user authorization could not be saved safely. Repair "
            "the local secrets directory permissions, then retry."
        ) from exc
    authorization = {
        "kind": contract.GITHUB_AUTH_KIND_USER_AUTHORIZATION,
        "refresh_credential_ref": str(credential_path),
        "status": "authorized",
    }
    snapshot: dict[str, Any] | None = None
    discovery_error: github_app_user_api.GitHubAppUserApiError | None = None
    try:
        snapshot = github_app_user_api.discover_access(
            api_url=metadata["api_url"],
            access_token=str(device.token_response["access_token"]),
            opener=api_opener,
        )
        authorization.update({
            "github_user_id": snapshot["user"]["id"],
            "login": snapshot["user"]["login"],
        })
    except github_app_user_api.GitHubAppUserApiError as exc:
        discovery_error = exc
    github = state.github_entry(
        metadata,
        authorization,
        snapshot,
        cached_snapshot=existing if discovery_error is not None else None,
    )
    try:
        mutation = writer.set_github(
            github, expected_credential_ref=expected_credential_ref,
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        try:
            state.remove_owned_credential(credential_path)
        except (OSError, ValueError) as cleanup_exc:
            raise GitHubMachineError(
                f"{exc}; the new local credential could not be cleaned up "
                "safely, so run `yoke github disconnect` before retrying"
            ) from cleanup_exc
        raise GitHubMachineError(str(exc)) from exc
    cleanup_issue: dict[str, str] | None = None
    replaced_ref = str(mutation["replaced_credential_ref"] or "")
    if replaced_ref and replaced_ref != str(credential_path):
        try:
            state.remove_owned_credential(Path(replaced_ref))
        except (OSError, ValueError):
            cleanup_issue = reports.issue(
                "warning", "github_previous_credential_not_removed",
                "The previous local GitHub App credential could not be removed safely",
                "Run `yoke github disconnect`, then reconnect GitHub.",
            )
    report = state.connected_report(
        config_path=config_path, github=github, progress=progress,
        checked=True, discovery_error=discovery_error,
    )
    report["operation"] = "github.connect"
    if cleanup_issue:
        report["issues"].append(cleanup_issue)
    if snapshot is not None and (
        not snapshot["installations"] or add_installation
    ):
        _open_install_page(
            report, browser_open=browser_open, notify=record,
            pending=not snapshot["installations"],
        )
        report["progress"] = progress
    return report


def status(
    *,
    config_path: str | Path | None,
    check: bool = True,
    api_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    try:
        github = state.existing_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise GitHubMachineError(str(exc)) from exc
    if not github:
        return reports.not_configured(config_path, None)
    if not check:
        return state.connected_report(
            config_path=config_path, github=github, progress=[], checked=False,
        )
    expected_credential_ref = state.credential_ref(github)
    try:
        token = github_user_tokens.access_token_from_machine_config(
            config_path=config_path, opener=token_opener, now=now
        )
        if token.refresh_credential_ref != expected_credential_ref:
            raise GitHubMachineError(
                "machine GitHub App authorization changed while status was "
                "running; retry against the current connection"
            )
        snapshot = github_app_user_api.discover_access(
            api_url=str(github["api_url"]), access_token=token.access_token,
            opener=api_opener,
        )
    except github_user_tokens.GitHubUserTokenError:
        return state.connected_report(
            config_path=config_path, github=github, progress=[], checked=True,
            token_error=(
                "GitHub App user authorization could not provide a valid access "
                "token"
            ),
        )
    except github_app_user_api.GitHubAppUserApiError as exc:
        persistence_error = None
        if exc.status == 401:
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
        return report
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
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise GitHubMachineError(str(exc)) from exc
    return state.connected_report(
        config_path=config_path, github=refreshed, progress=[], checked=True,
    )


def disconnect(*, config_path: str | Path | None) -> dict[str, Any]:
    """Forget local authorization without uninstalling the App from GitHub."""
    try:
        result = writer.clear_github(path=config_path)
    except writer.MachineConfigWriteError as exc:
        raise GitHubMachineError(str(exc)) from exc
    removed = False
    issue: dict[str, str] | None = None
    credential_ref = str(result["removed_credential_ref"] or "")
    if credential_ref:
        try:
            removed = state.remove_owned_credential(Path(credential_ref))
        except (OSError, ValueError):
            issue = reports.issue(
                "warning", "github_credential_not_removed",
                "The local GitHub App credential could not be removed safely",
                "Repair the local secrets directory permissions, then retry disconnect.",
            )
    return {
        "ok": issue is None,
        "operation": "github.disconnect",
        "configured": False,
        "config_path": result["config"],
        "credential_removed": removed,
        "github_app_uninstalled": False,
        "issues": [issue] if issue else [],
    }


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


render_human = reports.render_human


def _open_install_page(
    report: dict[str, Any], *, browser_open: Callable[[str], Any] | None,
    notify: Callable[[Mapping[str, Any]], None] | None, pending: bool,
) -> None:
    import webbrowser

    install_url = str(report.get("install_url") or "").strip()
    if not install_url:
        raise GitHubMachineError(
            "GitHub App installation URL is unavailable because the configured "
            "GitHub endpoints are invalid"
        )
    opened = False
    try:
        opened = bool((browser_open or webbrowser.open)(install_url))
    except Exception:
        pass
    report.update({"install_url": install_url, "install_browser_opened": opened})
    if pending:
        report["state"] = "pending_installation"
    if notify is not None:
        notify({"phase": "app_installation", "install_url": install_url,
                "browser_opened": opened})


__all__ = [
    "GitHubMachineError", "connect", "disconnect", "dumps_json",
    "render_human", "status",
]
