"""Machine-level GitHub App authorization for the product CLI."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping
import uuid

from yoke_cli.config import github_app_user_api
from yoke_cli.config import github_device_flow
from yoke_cli.config import github_machine_access
from yoke_cli.config import github_machine_add_installation
from yoke_cli.config import github_repo_helper_reconnect
from yoke_cli.config import github_machine_disconnect
from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_git_credential_document
from yoke_cli.config import github_machine_operation
from yoke_cli.config import github_machine_profile
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import github_machine_status
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import github_user_tokens
from yoke_cli.config import machine_config, writer
from yoke_contracts.machine_config import schema as contract

class GitHubMachineError(RuntimeError):
    """The machine GitHub App connection cannot be used."""


_serialized_machine_github = github_machine_operation.serialized_operation(
    GitHubMachineError
)


@_serialized_machine_github
def connect(
    *,
    config_path: str | Path | None,
    client_id: str | None = None,
    app_slug: str | None = None,
    app_id: int | str | None = None,
    api_url: str | None = None,
    web_url: str | None = None,
    service_api_url: str | None = None,
    use_local_product_profile: bool = False,
    profile_opener: Callable[..., Any] | None = None,
    replace_profile: bool = False,
    add_installation: bool = False,
    device_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
    api_opener: Callable[..., Any] | None = None,
    browser_open: Callable[[str], Any] | None = None,
    notify: Callable[[Mapping[str, Any]], None] | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Authorize the App user, discover installations, and persist metadata."""
    try:
        github_git_credentials.refresh_installed_helper()
    except (OSError, github_git_credentials.GitHubCredentialBundleError) as exc:
        raise GitHubMachineError(
            "The installed GitHub credential helper could not be upgraded; "
            "repair the Python installation permissions before reconnecting"
        ) from exc
    existing, metadata = github_machine_profile.resolve(
        config_path=config_path,
        client_id=client_id,
        app_slug=app_slug,
        app_id=app_id,
        api_url=api_url,
        web_url=web_url,
        service_api_url=service_api_url,
        use_local_product_profile=use_local_product_profile,
        profile_opener=profile_opener,
        replace_profile=replace_profile,
        error_type=GitHubMachineError,
    )
    _cleanup_removed, prior_cleanup_failures = (
        state.cleanup_quarantined_credentials(config_path)
    )
    progress: list[dict[str, Any]] = []

    def record(event: Mapping[str, Any]) -> None:
        public_event = dict(event)
        progress.append(
            github_machine_access.report_safe_progress_event(public_event)
        )
        if notify is not None:
            notify(public_event)

    if add_installation and existing:
        report = github_machine_add_installation.add_installation(
            config_path=config_path,
            github=existing,
            metadata=metadata,
            profile_opener=profile_opener,
            token_opener=token_opener,
            api_opener=api_opener,
            browser_open=browser_open,
            notify=record,
            sleep=sleep or time.sleep,
            error_type=GitHubMachineError,
        )
        report["progress"] = progress
        return report

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
    credential_path = (
        github_git_credential_document.machine_secrets_dir()
        / github_git_credential_document.credential_file_name(uuid.uuid4().hex)
    )
    try:
        github_user_tokens.store_initial_token(
            credential_path, device.token_response, now=now,
            device_flow_completed=True,
            config_path=machine_config.config_path(config_path),
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
        snapshot = _discover_access_with_unauthorized_retry(
            api_url=metadata["api_url"],
            access_token=str(device.token_response["access_token"]),
            opener=api_opener,
            sleep=sleep or time.sleep,
            notify=record,
            web_url=metadata["web_url"],
            expected_app_id=metadata["app_id"],
            expected_app_slug=metadata["app_slug"],
        )
        authorization.update({
            "github_user_id": snapshot["user"]["id"],
            "login": snapshot["user"]["login"],
        })
    except github_app_user_api.GitHubAppUserApiError as exc:
        discovery_error = exc
    if existing and discovery_error is not None:
        try:
            _cleanup_new_credential(credential_path, config_path=config_path)
        except (OSError, ValueError) as cleanup_exc:
            raise GitHubMachineError(
                "The replacement GitHub authorization could not be verified, "
                "and its unused local credential is pending safe cleanup; the "
                "previous connection was preserved"
            ) from cleanup_exc
        raise GitHubMachineError(
            "The replacement GitHub authorization could not be verified; the "
            "previous connection and credential were preserved. Retry reconnect "
            "when GitHub is available."
        ) from discovery_error
    github = state.github_entry(
        metadata,
        authorization,
        snapshot,
        cached_snapshot=existing if discovery_error is not None else None,
    )
    try:
        write_result = writer.set_github(
            github, expected_credential_ref=expected_credential_ref,
            expected_profile_identity=state.profile_identity(existing),
            path=config_path,
        )
    except BaseException as exc:
        try:
            current = state.existing_config(config_path)
            if state.credential_ref(current) != str(credential_path):
                _cleanup_new_credential(
                    credential_path, config_path=config_path,
                )
        except (OSError, ValueError) as cleanup_exc:
            raise GitHubMachineError(
                "The machine config write and local GitHub credential rollback "
                "could not complete safely, so run `yoke github disconnect` "
                "before retrying"
            ) from cleanup_exc
        if isinstance(exc, writer.MachineConfigWriteError):
            raise GitHubMachineError(str(exc)) from exc
        raise
    cleanup_issue: dict[str, str] | None = None
    cleanup = write_result.get("credential_cleanup") or {}
    if cleanup.get("pending"):
        cleanup_issue = reports.issue(
            "warning", "github_previous_credential_not_removed",
            "The previous local GitHub App credential is pending safe deletion",
            "Run `yoke github disconnect` again to retry safe cleanup.",
        )
    report = state.connected_report(
        config_path=config_path, github=github, progress=progress,
        checked=True, discovery_error=discovery_error,
    )
    report["operation"] = "github.connect"
    helper_reattach = github_repo_helper_reconnect.reattach(config_path)
    report["repo_helpers_reattached"] = helper_reattach["reattached"]
    report["repo_helpers_removed"] = helper_reattach["removed"]
    if helper_reattach["failed"]:
        report["issues"].append(reports.issue(
            "warning", "github_repo_helper_reattach_pending",
            f"{helper_reattach['failed']} registered GitHub checkout helper "
            "chain(s) need repair after saving the connection",
            "Re-run project onboarding for that checkout after repairing its Git remote/helper config.",
        ))
    if cleanup_issue:
        report["issues"].append(cleanup_issue)
    if prior_cleanup_failures:
        report["issues"].append(reports.issue(
            "warning",
            "github_credential_cleanup_pending",
            "An earlier quarantined GitHub App credential is still pending deletion",
            "Run `yoke github disconnect` again after repairing local permissions.",
        ))
    if snapshot is not None and (
        not snapshot["installations"] or add_installation
    ):
        _open_install_page(
            report, browser_open=browser_open, notify=record,
            pending=not snapshot["installations"],
        )
        report["progress"] = progress
    return report


@_serialized_machine_github
def status(
    *,
    config_path: str | Path | None,
    check: bool = True,
    api_opener: Callable[..., Any] | None = None,
    token_opener: Callable[..., Any] | None = None,
    service_api_url: str | None = None,
    profile_opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return github_machine_status.status(
        config_path=config_path,
        check=check,
        api_opener=api_opener,
        token_opener=token_opener,
        service_api_url=service_api_url,
        profile_opener=profile_opener,
        sleep=sleep,
        now=now,
        error_type=GitHubMachineError,
    )


@_serialized_machine_github
def disconnect(*, config_path: str | Path | None) -> dict[str, Any]:
    """Forget local authorization without uninstalling the App from GitHub."""
    return github_machine_disconnect.disconnect(
        config_path=config_path,
        error_type=GitHubMachineError,
    )


def _cleanup_new_credential(
    path: Path,
    *,
    config_path: str | Path | None,
) -> None:
    if config_path is None:
        raise ValueError("machine config path is required for credential cleanup")
    state.release_config_credential(path, machine_config.config_path(config_path))


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


render_human = reports.render_human


_discover_access_with_unauthorized_retry = (
    github_machine_access.discover_access_with_unauthorized_retry
)


def _open_install_page(
    report: dict[str, Any], *, browser_open: Callable[[str], Any] | None,
    notify: Callable[[Mapping[str, Any]], None] | None, pending: bool,
) -> None:
    github_machine_access.open_install_page(
        report,
        browser_open=browser_open,
        notify=notify,
        pending=pending,
        error_type=GitHubMachineError,
    )


__all__ = [
    "GitHubMachineError", "connect", "disconnect", "dumps_json",
    "render_human", "status",
]
