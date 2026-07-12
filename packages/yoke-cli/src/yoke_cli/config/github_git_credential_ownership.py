"""Config ownership mutations for shared GitHub refresh credentials."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from yoke_cli.config import github_git_credential_document as credential_document
from yoke_cli.config import github_git_credential_file as credential_file


def credential_document_from_token_response(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    schema_version, error_type = _store_contract()
    token_state = credential_document.token_state_from_response(
        payload,
        now=now,
        error_type=error_type,
    )
    document = credential_document.persisted_document(
        token_state,
        schema_version=schema_version,
        error_type=error_type,
    )
    if config_path is not None:
        owner = credential_document.config_owner(
            config_path,
            error_type=error_type,
        )
        document[credential_document.CONFIG_OWNERS_KEY] = [owner]
        document[credential_document.OWNERSHIP_COMPLETE_KEY] = True
    return document


def claim_config_owner(
    path: str | Path,
    config_path: str | Path,
) -> bool:
    """Claim a credential before a config commit; stale claims leak safely."""

    schema_version, error_type = _store_contract()
    owner = credential_document.config_owner(config_path, error_type=error_type)
    selected = Path(path).expanduser()
    with _locked(selected, error_type=error_type):
        current = _read(selected, schema_version=schema_version, error_type=error_type)
        owners = credential_document.config_owners(current, error_type=error_type)
        if owner in owners:
            return False
        current[credential_document.CONFIG_OWNERS_KEY] = [*owners, owner]
        current[credential_document.OWNERSHIP_COMPLETE_KEY] = (
            current.get(credential_document.OWNERSHIP_COMPLETE_KEY) is True
        )
        _write(
            selected,
            credential_document.persisted_document(
                current,
                schema_version=schema_version,
                error_type=error_type,
                ownership_source=current,
            ),
            error_type=error_type,
        )
    return True


def release_config_owner(
    path: str | Path,
    config_path: str | Path,
) -> dict[str, Any]:
    """Release one config and report whether deletion is proven safe."""

    schema_version, error_type = _store_contract()
    owner = credential_document.config_owner(config_path, error_type=error_type)
    selected = Path(path).expanduser()
    with _locked(selected, error_type=error_type):
        current = _read(selected, schema_version=schema_version, error_type=error_type)
        owners = credential_document.config_owners(current, error_type=error_type)
        complete = current.get(credential_document.OWNERSHIP_COMPLETE_KEY) is True
        if owner not in owners:
            return {
                "released": False,
                "remaining_owners": owners,
                "safe_to_delete": complete and not owners,
            }
        remaining = [item for item in owners if item != owner]
        current[credential_document.CONFIG_OWNERS_KEY] = remaining
        _write(
            selected,
            credential_document.persisted_document(
                current,
                schema_version=schema_version,
                error_type=error_type,
                ownership_source=current,
            ),
            error_type=error_type,
        )
    return {
        "released": True,
        "remaining_owners": remaining,
        "safe_to_delete": complete and not remaining,
    }


def _read(
    path: Path,
    *,
    schema_version: int,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    return credential_document.read_document(
        path,
        schema_version=schema_version,
        error_type=error_type,
    )


def _write(
    path: Path,
    payload: Mapping[str, Any],
    *,
    error_type: type[RuntimeError],
) -> None:
    credential_document.write_document(path, payload, error_type=error_type)


def _store_contract() -> tuple[int, type[RuntimeError]]:
    from yoke_cli.config.github_git_credential_store import (
        CREDENTIAL_SCHEMA_VERSION,
        GitHubCredentialStoreError,
    )

    return CREDENTIAL_SCHEMA_VERSION, GitHubCredentialStoreError


@contextmanager
def _locked(path: Path, *, error_type: type[RuntimeError]) -> Iterator[None]:
    try:
        with credential_file.exclusive_lock(path):
            yield
    except credential_file.CredentialFileError as exc:
        raise error_type(str(exc)) from exc


__all__ = [
    "claim_config_owner",
    "credential_document_from_token_response",
    "release_config_owner",
]
