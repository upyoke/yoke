"""Atomic machine GitHub disconnect and registered-checkout helper cleanup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_git_credentials
from yoke_cli.config import github_machine_report as reports
from yoke_cli.config import github_machine_state as state
from yoke_cli.config import machine_config, writer


def disconnect(
    *,
    config_path: str | Path | None,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    """Forget local auth after quarantining its exact referenced credential."""
    cleaned, cleanup_failures = state.cleanup_quarantined_credentials(config_path)
    try:
        existing = state.existing_config(config_path)
    except machine_config.MachineConfigError as exc:
        raise error_type(str(exc)) from exc
    credential_ref = state.credential_ref(existing)
    external_credential = bool(
        credential_ref
        and not state.is_owned_credential_path(Path(credential_ref))
    )
    try:
        result = writer.clear_github(
            expected_credential_ref=credential_ref,
            path=config_path,
        )
    except writer.MachineConfigWriteError as exc:
        raise error_type(str(exc)) from exc

    cleanup = result.get("credential_cleanup") or {}
    removed = bool(cleaned or cleanup.get("removed"))
    issues: list[dict[str, str]] = []
    if external_credential:
        issues.append(reports.issue(
            "warning",
            "github_external_credential_left_untouched",
            "The GitHub connection was forgotten; its external credential "
            "file was left untouched",
            "Remove that external file yourself if it is no longer needed.",
        ))
    if cleanup.get("pending"):
        issues.append(reports.issue(
            "warning",
            "github_credential_not_removed",
            "The local GitHub App credential is pending safe deletion",
            "Repair local permissions, then run disconnect again.",
        ))
    elif cleanup.get("shared") and not external_credential:
        issues.append(reports.issue(
            "warning",
            "github_shared_credential_preserved",
            "The GitHub connection was forgotten, but its credential is shared "
            "or has incomplete legacy ownership metadata and was preserved",
            "Disconnect the other config owners before removing the credential.",
        ))
    if cleanup_failures:
        issues.append(reports.issue(
            "warning",
            "github_credential_cleanup_pending",
            "A quarantined GitHub App credential is still pending deletion",
            "Repair local permissions, then run disconnect again.",
        ))
    helper_cleanup = github_git_credentials.remove_known_repo_helpers(
        config_path=config_path,
    )
    if helper_cleanup["failed"]:
        issues.append(reports.issue(
            "warning",
            "github_repo_helper_cleanup_pending",
            "A registered checkout still has Yoke's GitHub credential helper",
            "Run `yoke github disconnect` again after repairing that checkout.",
        ))
    cleanup_pending = any(
        item["code"] in {
            "github_credential_not_removed",
            "github_credential_cleanup_pending",
            "github_repo_helper_cleanup_pending",
        }
        for item in issues
    )
    return {
        "ok": not cleanup_pending,
        "operation": "github.disconnect",
        "configured": False,
        "config_path": result["config"],
        "credential_removed": removed,
        "credential_cleanup_pending": any(
            item["code"].startswith("github_credential") for item in issues
        ),
        "repo_helpers_removed": helper_cleanup["removed"],
        "github_app_uninstalled": False,
        "issues": issues,
    }


__all__ = ["disconnect"]
