"""Shared machine credential-source contract constants."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)

CREDENTIAL_KIND_DSN_FILE = "dsn_file"
CREDENTIAL_KIND_ENV = "env"
CREDENTIAL_KIND_AWS_SECRETS_MANAGER = "aws_secrets_manager"
CREDENTIAL_KIND_TOKEN_FILE = "token_file"

CREDENTIAL_KINDS = frozenset({
    CREDENTIAL_KIND_DSN_FILE,
    CREDENTIAL_KIND_ENV,
    CREDENTIAL_KIND_AWS_SECRETS_MANAGER,
    CREDENTIAL_KIND_TOKEN_FILE,
})
TOKEN_CREDENTIAL_KINDS = frozenset({
    CREDENTIAL_KIND_TOKEN_FILE,
})
GITHUB_CREDENTIAL_KINDS = TOKEN_CREDENTIAL_KINDS


def validate_credential_source(
    source: Mapping[str, Any],
    *,
    prefix: str,
) -> list[ValidationIssue]:
    kind = source.get("kind")
    if not _is_nonempty_str(kind) or str(kind) not in CREDENTIAL_KINDS:
        return [_error(
            "credential_kind_invalid",
            f"credential_source.kind must be one of {sorted(CREDENTIAL_KINDS)}",
            path=f"{prefix}.credential_source.kind",
        )]
    if (
        kind == CREDENTIAL_KIND_DSN_FILE
        and not _is_nonempty_str(source.get("path"))
    ):
        return [_error(
            "credential_dsn_file_path_required",
            "dsn_file credential_source requires path",
            path=f"{prefix}.credential_source.path",
        )]
    if kind == CREDENTIAL_KIND_ENV and not _is_nonempty_str(source.get("name")):
        return [_error(
            "credential_env_name_required",
            "env credential_source requires name",
            path=f"{prefix}.credential_source.name",
        )]
    if (
        kind == CREDENTIAL_KIND_TOKEN_FILE
        and not _is_nonempty_str(source.get("path"))
    ):
        return [_error(
            "credential_token_file_path_required",
            "token_file credential_source requires path",
            path=f"{prefix}.credential_source.path",
        )]
    return []


__all__ = [
    "CREDENTIAL_KIND_AWS_SECRETS_MANAGER",
    "CREDENTIAL_KIND_DSN_FILE",
    "CREDENTIAL_KIND_ENV",
    "CREDENTIAL_KIND_TOKEN_FILE",
    "CREDENTIAL_KINDS",
    "GITHUB_CREDENTIAL_KINDS",
    "TOKEN_CREDENTIAL_KINDS",
    "validate_credential_source",
]
