"""Refresh-only GitHub credential document validation and token timing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
from typing import Any, Mapping

if __package__:
    from yoke_contracts import github_app_tokens as token_contract
else:  # pragma: no cover - copied helper uses its immutable sibling
    import _yoke_github_app_tokens as token_contract  # type: ignore
if __package__:
    from yoke_cli.config import github_git_credential_file as credential_file
else:  # pragma: no cover - copied helper uses its immutable sibling
    import _yoke_github_git_credential_file as credential_file  # type: ignore


_CREDENTIAL_ID = re.compile(r"[0-9a-f]{32}")
CREDENTIAL_FILE_PREFIX = "github-app-user-"
CREDENTIAL_FILE_SUFFIX = ".json"
CREDENTIAL_QUARANTINE_SUFFIX = ".pending-delete.json"
LIVE_CREDENTIAL_GLOB = f"{CREDENTIAL_FILE_PREFIX}*{CREDENTIAL_FILE_SUFFIX}"
QUARANTINED_CREDENTIAL_GLOB = (
    f"{CREDENTIAL_FILE_PREFIX}*{CREDENTIAL_QUARANTINE_SUFFIX}"
)
_MACHINE_HOME_ENV = "YOKE_MACHINE_HOME"
_MACHINE_SECRETS_DIR_NAME = "secrets"
CONFIG_OWNERS_KEY = "config_owners"
OWNERSHIP_COMPLETE_KEY = "config_ownership_complete"


def validate_owned_path(
    config_path: str | Path | None,
    credential_path: str | Path,
    *,
    error_type: type[RuntimeError],
) -> Path:
    """Require a generated credential inside this machine's Yoke secret dir."""

    if config_path is None:
        raise error_type("machine config path is required")
    selected = Path(credential_path).expanduser()
    machine_home = os.environ.get(_MACHINE_HOME_ENV, "").strip()
    secret_dir = (
        Path(machine_home).expanduser() / _MACHINE_SECRETS_DIR_NAME
        if machine_home
        else _default_machine_home() / _MACHINE_SECRETS_DIR_NAME
    )
    if (
        not selected.is_absolute()
        or not is_live_credential_name(selected.name)
    ):
        raise error_type(
            "GitHub App credential reference is not Yoke-owned; reconnect GitHub"
        )
    try:
        expected_parent = secret_dir.resolve(strict=False)
        actual_parent = selected.parent.resolve(strict=False)
        resolved_selected = selected.resolve(strict=False)
    except OSError as exc:
        raise error_type(
            "GitHub App credential reference is unsafe; reconnect GitHub"
        ) from exc
    if (
        actual_parent != expected_parent
        or resolved_selected != expected_parent / selected.name
    ):
        raise error_type(
            "GitHub App credential reference is not Yoke-owned; reconnect GitHub"
        )
    return selected


def _default_machine_home() -> Path:
    return Path.home() / ".yoke"


def machine_secrets_dir() -> Path:
    machine_home = os.environ.get(_MACHINE_HOME_ENV, "").strip()
    return (
        Path(machine_home).expanduser()
        if machine_home else _default_machine_home()
    ) / _MACHINE_SECRETS_DIR_NAME


def credential_file_name(credential_id: str) -> str:
    """Return the single supported live credential filename."""

    if _CREDENTIAL_ID.fullmatch(str(credential_id or "")) is None:
        raise ValueError("GitHub App credential id must be 32 lowercase hex characters")
    return f"{CREDENTIAL_FILE_PREFIX}{credential_id}{CREDENTIAL_FILE_SUFFIX}"


def is_live_credential_name(name: str) -> bool:
    value = str(name or "")
    if not (
        value.startswith(CREDENTIAL_FILE_PREFIX)
        and value.endswith(CREDENTIAL_FILE_SUFFIX)
    ):
        return False
    credential_id = value[
        len(CREDENTIAL_FILE_PREFIX):-len(CREDENTIAL_FILE_SUFFIX)
    ]
    return _CREDENTIAL_ID.fullmatch(credential_id) is not None


def quarantined_credential_name(live_name: str) -> str:
    if not is_live_credential_name(live_name):
        raise ValueError("GitHub App credential filename is invalid")
    return (
        live_name.removesuffix(CREDENTIAL_FILE_SUFFIX)
        + CREDENTIAL_QUARANTINE_SUFFIX
    )


def is_quarantined_credential_name(name: str) -> bool:
    value = str(name or "")
    if not value.endswith(CREDENTIAL_QUARANTINE_SUFFIX):
        return False
    live_name = (
        value.removesuffix(CREDENTIAL_QUARANTINE_SUFFIX)
        + CREDENTIAL_FILE_SUFFIX
    )
    return is_live_credential_name(live_name)


def read_document(
    path: str | Path,
    *,
    schema_version: int,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    try:
        payload = credential_file.read_json_document(path)
    except credential_file.CredentialFileError as exc:
        raise error_type(str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != schema_version:
        raise error_type(
            "GitHub App credential has an unsupported format; reconnect GitHub"
        )
    required_string(payload.get("refresh_token"), "refresh_token", error_type)
    parse_timestamp(payload.get("refresh_expires_at"), "refresh_expires_at", error_type)
    forbidden = {"access_token", "expires_at", "scope", "token_type"} & set(payload)
    if forbidden:
        raise error_type(
            "GitHub App credential contains access-token state; reconnect GitHub"
        )
    return payload


def write_document(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    error_type: type[RuntimeError],
) -> Path:
    try:
        return credential_file.write_json_document(path, payload)
    except credential_file.CredentialFileError as exc:
        raise error_type(str(exc)) from exc
    except OSError as exc:
        raise error_type(
            f"GitHub App credential could not be saved: {Path(path).expanduser()}"
        ) from exc


def token_state_from_response(
    payload: Mapping[str, Any],
    *,
    now: datetime | None,
    error_type: type[RuntimeError],
) -> dict[str, Any]:
    selected_now = ensure_utc(now or datetime.now(timezone.utc))
    try:
        return {
            "access_token": required_string(
                payload.get("access_token"), "access_token", error_type,
            ),
            "expires_at": expiry_timestamp(
                payload.get("expires_in"), now=selected_now, label="expires_in",
                maximum=token_contract.GITHUB_APP_USER_ACCESS_TOKEN_MAX_SECONDS,
                error_type=error_type,
            ).isoformat(),
            "refresh_token": required_string(
                payload.get("refresh_token"), "refresh_token", error_type,
            ),
            "refresh_expires_at": expiry_timestamp(
                payload.get("refresh_token_expires_in"),
                now=selected_now,
                label="refresh_token_expires_in",
                maximum=token_contract.GITHUB_APP_USER_REFRESH_TOKEN_MAX_SECONDS,
                error_type=error_type,
            ).isoformat(),
            "scope": str(payload.get("scope") or ""),
            "token_type": str(payload.get("token_type") or "bearer"),
        }
    except error_type as exc:
        raise error_type(
            f"{exc}. {token_contract.GITHUB_APP_USER_AUTH_CONFIGURATION_HINT}"
        ) from exc


def persisted_document(
    payload: Mapping[str, Any],
    *,
    schema_version: int,
    error_type: type[RuntimeError],
    ownership_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = ownership_source if ownership_source is not None else payload
    return {
        "schema_version": schema_version,
        "refresh_token": required_string(
            payload.get("refresh_token"), "refresh_token", error_type,
        ),
        "refresh_expires_at": parse_timestamp(
            payload.get("refresh_expires_at"),
            "refresh_expires_at",
            error_type,
        ).isoformat(),
        CONFIG_OWNERS_KEY: config_owners(source, error_type=error_type),
        OWNERSHIP_COMPLETE_KEY: source.get(OWNERSHIP_COMPLETE_KEY) is True,
    }


def config_owner(value: str | Path, *, error_type: type[RuntimeError]) -> str:
    """Return one stable absolute config identity for credential ownership."""

    selected = Path(value).expanduser()
    if not selected.is_absolute():
        raise error_type("machine config ownership path must be absolute")
    try:
        return str(selected.resolve(strict=False))
    except OSError as exc:
        raise error_type("machine config ownership path is unsafe") from exc


def config_owners(
    payload: Mapping[str, Any], *, error_type: type[RuntimeError],
) -> list[str]:
    raw = payload.get(CONFIG_OWNERS_KEY)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise error_type("GitHub App credential config owners must be a list")
    owners: list[str] = []
    for item in raw:
        owner = config_owner(item, error_type=error_type)
        if owner not in owners:
            owners.append(owner)
    return sorted(owners)


def required_string(
    value: Any, label: str, error_type: type[RuntimeError],
) -> str:
    if not isinstance(value, str):
        raise error_type(f"{label} must be a string")
    text = value.strip()
    if not text:
        raise error_type(f"{label} is required")
    return text


def expiry_timestamp(
    value: Any,
    *,
    now: datetime,
    label: str,
    maximum: int,
    error_type: type[RuntimeError],
) -> datetime:
    if isinstance(value, bool):
        raise error_type(f"{label} must be a positive integer")
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be a positive integer") from exc
    if seconds <= 0 or seconds > maximum:
        raise error_type(f"{label} must be a positive integer")
    try:
        return now + timedelta(seconds=seconds)
    except OverflowError as exc:
        raise error_type(f"{label} must be a positive integer") from exc


def parse_timestamp(
    value: Any, label: str, error_type: type[RuntimeError],
) -> datetime:
    try:
        return ensure_utc(datetime.fromisoformat(str(value)))
    except (TypeError, ValueError) as exc:
        raise error_type(f"{label} must be an ISO timestamp") from exc


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "CREDENTIAL_FILE_PREFIX",
    "CREDENTIAL_FILE_SUFFIX",
    "CREDENTIAL_QUARANTINE_SUFFIX",
    "CONFIG_OWNERS_KEY",
    "LIVE_CREDENTIAL_GLOB",
    "OWNERSHIP_COMPLETE_KEY",
    "QUARANTINED_CREDENTIAL_GLOB",
    "config_owner",
    "config_owners",
    "credential_file_name",
    "is_live_credential_name",
    "is_quarantined_credential_name",
    "machine_secrets_dir",
    "ensure_utc",
    "parse_timestamp",
    "persisted_document",
    "read_document",
    "required_string",
    "token_state_from_response",
    "quarantined_credential_name",
    "validate_owned_path",
    "write_document",
]
