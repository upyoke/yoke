"""Owned GitHub credential quarantine and cleanup lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import github_git_credential_document
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import machine_config, secrets


def remove_owned_credential(path: Path) -> bool:
    selected = path.expanduser()
    allowed = secrets.secrets_dir().resolve()
    resolved = selected.resolve(strict=False)
    if (
        not selected.is_absolute()
        or selected.parent.resolve(strict=False) != allowed
        or resolved.parent != allowed
        or not github_git_credential_document.is_live_credential_name(selected.name)
    ):
        raise ValueError(
            "refusing to remove a file that is not a Yoke-owned GitHub App "
            "user credential"
        )
    try:
        return github_git_credential_file.delete_json_document(selected)
    except github_git_credential_file.CredentialFileError as exc:
        raise ValueError(str(exc)) from exc


def is_owned_credential_path(path: Path) -> bool:
    try:
        _validated_owned_path(path, quarantine=False)
    except (OSError, ValueError):
        return False
    return True


def quarantine_owned_credential(path: Path) -> Path | None:
    """Move one exact live credential to a retryable non-live name."""
    selected = _validated_owned_path(path, quarantine=False)
    quarantine = selected.with_name(
        github_git_credential_document.quarantined_credential_name(selected.name)
    )
    try:
        moved = github_git_credential_file.quarantine_json_document(
            selected,
            quarantine,
        )
    except github_git_credential_file.CredentialFileError as exc:
        raise ValueError(str(exc)) from exc
    return quarantine if moved else None


def restore_quarantined_credential(quarantine: Path, original: Path) -> bool:
    selected_quarantine = _validated_owned_path(quarantine, quarantine=True)
    selected_original = _validated_owned_path(original, quarantine=False)
    try:
        return github_git_credential_file.restore_quarantined_json_document(
            selected_quarantine,
            selected_original,
        )
    except github_git_credential_file.CredentialFileError as exc:
        raise ValueError(str(exc)) from exc


def remove_quarantined_credential(path: Path) -> bool:
    selected = _validated_owned_path(path, quarantine=True)
    try:
        return github_git_credential_file.delete_json_document(selected)
    except github_git_credential_file.CredentialFileError as exc:
        raise ValueError(str(exc)) from exc


def cleanup_quarantined_credentials(
    config_path: str | Path | None = None,
) -> tuple[int, int]:
    """Delete orphaned owned credentials while protecting the live CAS ref."""

    removed = 0
    failed = 0
    try:
        current = _current_credential_ref(config_path)
        config_read = True
    except machine_config.MachineConfigError:
        current = ""
        config_read = False
    current_path = Path(current).expanduser() if current else None
    protected_quarantine = (
        current_path.with_name(
            github_git_credential_document.quarantined_credential_name(
                current_path.name
            )
        )
        if current_path and is_owned_credential_path(current_path)
        else None
    )
    for path in secrets.secrets_dir().glob(
        github_git_credential_document.QUARANTINED_CREDENTIAL_GLOB
    ):
        if not config_read or path == protected_quarantine:
            continue
        try:
            removed += int(remove_quarantined_credential(path))
        except (OSError, ValueError):
            failed += 1
    live_removed, live_failed = _cleanup_owned_live_credentials(
        config_path,
        current_path=current_path if config_read else None,
    )
    return removed + live_removed, failed + live_failed


def release_config_credential(
    path: Path,
    config_path: str | Path,
) -> dict[str, Any]:
    """Release a committed-away credential and delete only with complete ownership."""

    selected = _validated_owned_path(path, quarantine=False)
    try:
        release = github_git_credential_store.release_config_owner(
            selected,
            config_path,
        )
    except github_git_credential_store.GitHubCredentialStoreError as exc:
        raise ValueError(str(exc)) from exc
    removed = False
    if release.get("safe_to_delete") is True:
        removed = remove_owned_credential(selected)
    return {**release, "removed": removed}


def _cleanup_owned_live_credentials(
    config_path: str | Path | None,
    *,
    current_path: Path | None,
) -> tuple[int, int]:
    if config_path is None:
        return 0, 0
    try:
        owner = github_git_credential_document.config_owner(
            machine_config.config_path(config_path),
            error_type=ValueError,
        )
    except (OSError, ValueError):
        return 0, 0
    removed = 0
    failed = 0
    for path in secrets.secrets_dir().glob(
        github_git_credential_document.LIVE_CREDENTIAL_GLOB
    ):
        if current_path is not None and path == current_path:
            continue
        try:
            document = github_git_credential_store.read_credential_document(path)
            owners = github_git_credential_document.config_owners(
                document,
                error_type=github_git_credential_store.GitHubCredentialStoreError,
            )
            if (
                document.get(github_git_credential_document.OWNERSHIP_COMPLETE_KEY)
                is not True
            ):
                continue
            if not owners:
                removed += int(remove_owned_credential(path))
                continue
            if owner not in owners:
                continue
            release = release_config_credential(path, config_path)
            removed += int(release.get("removed") is True)
        except (
            OSError,
            ValueError,
            github_git_credential_store.GitHubCredentialStoreError,
        ):
            failed += 1
    return removed, failed


def _validated_owned_path(path: Path, *, quarantine: bool) -> Path:
    selected = path.expanduser()
    allowed = secrets.secrets_dir().resolve()
    resolved = selected.resolve(strict=False)
    valid_name = (
        github_git_credential_document.is_quarantined_credential_name(selected.name)
        if quarantine
        else github_git_credential_document.is_live_credential_name(selected.name)
    )
    if (
        not selected.is_absolute()
        or selected.parent.resolve(strict=False) != allowed
        or resolved.parent != allowed
        or not valid_name
    ):
        kind = "quarantined" if quarantine else "live"
        raise ValueError(
            f"refusing to mutate a file that is not a Yoke-owned {kind} "
            "GitHub App user credential"
        )
    return selected


def _current_credential_ref(config_path: str | Path | None) -> str:
    github = machine_config.github_config(config_path)
    authorization = github.get("authorization")
    if not isinstance(authorization, dict):
        return ""
    return str(authorization.get("refresh_credential_ref") or "").strip()
