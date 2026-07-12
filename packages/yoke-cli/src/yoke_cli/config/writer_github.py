"""Compare-and-swap machine-config writes for GitHub authorization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config import machine_config_file
from yoke_cli.config import github_git_credential_document
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_store
from yoke_contracts import github_app_tokens
from yoke_cli.config.machine_config_mutation import (
    MachineConfigWriteError,
    load_payload,
    serialized_mutation,
    write_payload,
)


@serialized_mutation
def set_github(
    github: Mapping[str, Any],
    *,
    expected_credential_ref: str,
    expected_profile_identity: Mapping[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Replace GitHub metadata iff its authorization is still expected."""

    payload, cfg_path = load_payload(path)
    replaced_ref = _github_credential_ref(payload.get("github"))
    if replaced_ref != expected_credential_ref:
        raise MachineConfigWriteError(
            "machine GitHub App authorization changed during this operation; "
            "retry against the current connection"
        )
    if (
        expected_profile_identity is not None
        and _github_profile_identity(payload.get("github"))
        != dict(expected_profile_identity)
    ):
        raise MachineConfigWriteError(
            "machine GitHub App profile changed during this operation; retry "
            "against the current connection"
        )
    entry = dict(github)
    selected_ref = _github_credential_ref(entry)
    claim_added = _claim_owned_credential(
        selected_ref, cfg_path,
    )
    payload["github"] = entry
    try:
        write_payload(payload, cfg_path)
    except BaseException:
        if claim_added:
            _release_owned_credential(selected_ref, cfg_path, delete=False)
        raise
    cleanup = (
        _release_owned_credential(replaced_ref, cfg_path, delete=True)
        if replaced_ref and replaced_ref != selected_ref
        else _credential_cleanup_report()
    )
    return {
        "github": dict(entry), "config": str(cfg_path),
        "replaced_credential_ref": replaced_ref,
        "credential_cleanup": cleanup,
    }


@serialized_mutation
def clear_github(
    *,
    expected_credential_ref: str | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Remove GitHub iff its authorization is still expected."""

    payload, cfg_path = load_payload(path)
    current_ref = _github_credential_ref(payload.get("github"))
    if (
        expected_credential_ref is not None
        and current_ref != expected_credential_ref
    ):
        raise MachineConfigWriteError(
            "machine GitHub App authorization changed during disconnect; "
            "retry against the current connection"
        )
    removed = payload.pop("github", None)
    configured = removed is not None
    removed_ref = _github_credential_ref(removed)
    if set(payload) <= {"schema_version"}:
        machine_config_file.remove_file(cfg_path)
    else:
        write_payload(payload, cfg_path)
    cleanup = _release_owned_credential(removed_ref, cfg_path, delete=True)
    return {
        "configured": configured, "config": str(cfg_path),
        "removed_credential_ref": removed_ref,
        "credential_cleanup": cleanup,
    }


def _github_credential_ref(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    authorization = value.get("authorization")
    if not isinstance(authorization, Mapping):
        return ""
    return str(authorization.get("refresh_credential_ref") or "").strip()


def _github_profile_identity(value: Any) -> dict[str, Any]:
    selected = value if isinstance(value, Mapping) else {}
    return {
        field: selected.get(field)
        for field in github_app_tokens.GITHUB_PROFILE_IDENTITY_FIELDS
    }


def _owned_credential_path(value: str, cfg_path: Path) -> Path | None:
    if not value:
        return None
    try:
        return github_git_credential_document.validate_owned_path(
            cfg_path,
            value,
            error_type=github_git_credential_store.GitHubCredentialStoreError,
        )
    except github_git_credential_store.GitHubCredentialStoreError:
        return None


def _claim_owned_credential(value: str, cfg_path: Path) -> bool:
    path = _owned_credential_path(value, cfg_path)
    if path is None:
        return False
    return github_git_credential_store.claim_config_owner(path, cfg_path)


def _credential_cleanup_report(
    *,
    released: bool = False,
    removed: bool = False,
    pending: bool = False,
    shared: bool = False,
) -> dict[str, bool]:
    return {
        "released": released,
        "removed": removed,
        "pending": pending,
        "shared": shared,
    }


def _release_owned_credential(
    value: str,
    cfg_path: Path,
    *,
    delete: bool,
) -> dict[str, bool]:
    path = _owned_credential_path(value, cfg_path)
    if path is None:
        return _credential_cleanup_report(shared=bool(value))
    try:
        release = github_git_credential_store.release_config_owner(path, cfg_path)
    except github_git_credential_store.GitHubCredentialStoreError:
        return _credential_cleanup_report(pending=True)
    safe_to_delete = release["safe_to_delete"] is True
    if not delete or not safe_to_delete:
        return _credential_cleanup_report(
            released=release["released"] is True,
            shared=bool(release["remaining_owners"]) or not safe_to_delete,
        )
    try:
        removed = github_git_credential_file.delete_json_document(path)
    except github_git_credential_file.CredentialFileError:
        return _credential_cleanup_report(released=True, pending=True)
    return _credential_cleanup_report(released=True, removed=removed)


__all__ = ["clear_github", "set_github"]
