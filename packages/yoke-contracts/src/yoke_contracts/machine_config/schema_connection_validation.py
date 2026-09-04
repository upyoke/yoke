"""Validation for one machine-config connection entry."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_config.credential_sources import (
    TOKEN_CREDENTIAL_KINDS,
    validate_credential_source,
)
from yoke_contracts.machine_config.schema_connections import PROD_FLAG_KEY
from yoke_contracts.machine_config.schema_projects import (
    ValidationIssue,
    _error,
    _is_nonempty_str,
)
from yoke_contracts.machine_config.schema_transport import (
    POSTGRES_TRANSPORTS,
    TRANSPORTS,
    TRANSPORT_HTTPS,
)


TUNNEL_REQUIRED_KEYS = ("bastion", "identity_file", "remote_host", "remote_port")


def validate_connection(
    env_label: str,
    connection: Mapping[str, Any],
) -> list[ValidationIssue]:
    """Validate transport, credentials, and optional tunnel configuration."""
    prefix = f"connections.{env_label}"
    issues: list[ValidationIssue] = []
    transport = connection.get("transport")
    if not _is_nonempty_str(transport) or str(transport) not in TRANSPORTS:
        issues.append(
            _error(
                "transport_invalid",
                f"{prefix}.transport must be one of {sorted(TRANSPORTS)}",
                path=f"{prefix}.transport",
            )
        )
    source = connection.get("credential_source")
    if not isinstance(source, Mapping):
        issues.append(
            _error(
                "credential_source_required",
                f"{prefix}.credential_source must be an object",
                path=f"{prefix}.credential_source",
            )
        )
    else:
        issues.extend(validate_credential_source(source, prefix=prefix))
    if PROD_FLAG_KEY in connection and not isinstance(
        connection.get(PROD_FLAG_KEY), bool
    ):
        issues.append(
            _error(
                "prod_flag_invalid",
                f"{prefix}.{PROD_FLAG_KEY} must be a boolean when present",
                path=f"{prefix}.{PROD_FLAG_KEY}",
            )
        )
    if str(transport) in POSTGRES_TRANSPORTS:
        postgres = connection.get("postgres")
        if postgres is not None and not isinstance(postgres, Mapping):
            issues.append(
                _error(
                    "postgres_invalid",
                    f"{prefix}.postgres must be an object",
                    path=f"{prefix}.postgres",
                )
            )
        elif isinstance(postgres, Mapping):
            issues.extend(_validate_tunnel(postgres.get("tunnel"), prefix=prefix))
    if str(transport) == TRANSPORT_HTTPS:
        if not _is_nonempty_str(connection.get("api_url")):
            issues.append(
                _error(
                    "api_url_required",
                    "https transport requires api_url",
                    path=f"{prefix}.api_url",
                )
            )
        kind = source.get("kind") if isinstance(source, Mapping) else None
        if kind not in TOKEN_CREDENTIAL_KINDS:
            issues.append(
                _error(
                    "https_credential_kind_invalid",
                    "https transport requires credential_source.kind 'token_file'",
                    path=f"{prefix}.credential_source.kind",
                )
            )
    return issues


def _validate_tunnel(tunnel: Any, *, prefix: str) -> list[ValidationIssue]:
    """A declared tunnel block must be complete or the self-heal is dead."""
    if tunnel is None:
        return []
    if not isinstance(tunnel, Mapping):
        return [
            _error(
                "tunnel_invalid",
                f"{prefix}.postgres.tunnel must be an object",
                path=f"{prefix}.postgres.tunnel",
            )
        ]
    missing = [key for key in TUNNEL_REQUIRED_KEYS if not tunnel.get(key)]
    if missing:
        return [
            _error(
                "tunnel_incomplete",
                f"{prefix}.postgres.tunnel is missing {', '.join(missing)}; "
                "an incomplete tunnel block disables connected-env self-heal",
                path=f"{prefix}.postgres.tunnel",
                hint=f"Declare all of: {', '.join(TUNNEL_REQUIRED_KEYS)}.",
            )
        ]
    return []


__all__ = ["TUNNEL_REQUIRED_KEYS", "validate_connection"]
