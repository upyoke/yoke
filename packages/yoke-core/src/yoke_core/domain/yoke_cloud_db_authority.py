"""Helpers for resolving Yoke cloud Postgres authority.

This module is intentionally small: it converts declared stack/output facts
and a Secrets Manager JSON payload into a libpq DSN. Live Pulumi, AWS, and SSH
commands stay explicit operator-attended steps; tests exercise only parsing and
DSN construction.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_ENDPOINT_OUTPUT = "databaseClusterEndpoint"
DEFAULT_SECRET_ARN_OUTPUT = "databaseSecretArn"
DEFAULT_POSTGRES_PORT = 5432


@dataclass(frozen=True)
class PostgresAuthorityLocation:
    stack: str
    database_name: str
    endpoint_output: str = DEFAULT_ENDPOINT_OUTPUT
    secret_arn_output: str = DEFAULT_SECRET_ARN_OUTPUT
    state_backend: Optional[str] = None
    region: Optional[str] = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PostgresAuthorityLocation":
        return cls(
            stack=_required_str(value, "stack"),
            database_name=_required_str(value, "database_name"),
            endpoint_output=str(value.get("endpoint_output") or DEFAULT_ENDPOINT_OUTPUT),
            secret_arn_output=str(value.get("secret_arn_output") or DEFAULT_SECRET_ARN_OUTPUT),
            state_backend=_optional_str(value, "state_backend"),
            region=_optional_str(value, "region"),
        )

    def as_settings_location(self) -> dict:
        out = {
            "stack": self.stack,
            "database_name": self.database_name,
            "endpoint_output": self.endpoint_output,
            "secret_arn_output": self.secret_arn_output,
        }
        if self.state_backend:
            out["state_backend"] = self.state_backend
        if self.region:
            out["region"] = self.region
        return out


@dataclass(frozen=True)
class PostgresSecret:
    username: str
    password: str
    engine: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None

    @classmethod
    def from_json(cls, raw: str) -> "PostgresSecret":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"database secret is not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("database secret JSON must be an object")
        return cls(
            username=_required_str(payload, "username"),
            password=_required_str(payload, "password"),
            engine=_optional_str(payload, "engine"),
            host=_optional_str(payload, "host"),
            port=_optional_int(payload, "port"),
        )


def load_stack_outputs(
    infra_dir: Path,
    location: PostgresAuthorityLocation,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Mapping[str, Any]:
    """Read Pulumi stack outputs as JSON without exposing secrets.

    ``env`` lets callers materialize capability-owned AWS credentials into
    the subprocess environment instead of relying on ambient shell state.
    """
    subprocess_env = dict(env) if env is not None else None
    if location.state_backend:
        subprocess.run(
            ["pulumi", "login", location.state_backend],
            cwd=str(infra_dir),
            check=True,
            capture_output=True,
            text=True,
            env=subprocess_env,
        )
    proc = subprocess.run(
        ["pulumi", "stack", "output", "--stack", location.stack, "--json"],
        cwd=str(infra_dir),
        check=True,
        capture_output=True,
        text=True,
        env=subprocess_env,
    )
    parsed = json.loads(proc.stdout or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Pulumi stack output JSON must be an object")
    return parsed


def load_secret_string(
    secret_arn: str,
    *,
    region: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Read the RDS secret JSON string from AWS Secrets Manager."""
    cmd = [
        "aws",
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        secret_arn,
        "--query",
        "SecretString",
        "--output",
        "text",
    ]
    if region:
        cmd.extend(["--region", region])
    proc = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
    )
    return proc.stdout.strip()


def endpoint_and_secret_arn(
    outputs: Mapping[str, Any],
    location: PostgresAuthorityLocation,
) -> tuple[str, str]:
    endpoint = _required_str(outputs, location.endpoint_output)
    secret_arn = _required_str(outputs, location.secret_arn_output)
    return endpoint, secret_arn


def build_libpq_dsn(
    *,
    host: str,
    database: str,
    secret: PostgresSecret,
    port: int = DEFAULT_POSTGRES_PORT,
) -> str:
    """Build a libpq key/value DSN, safely quoting user-controlled values."""
    parts = {
        "host": host,
        "port": str(port),
        "user": secret.username,
        "password": secret.password,
        "dbname": database,
    }
    return " ".join(f"{key}={shlex.quote(value)}" for key, value in parts.items())


def redacted_dsn(dsn: str) -> str:
    parts = []
    for token in shlex.split(dsn):
        if token.startswith("password="):
            parts.append("password=<redacted>")
        else:
            parts.append(token)
    return " ".join(parts)


def resolve_declared_dsn(
    *,
    infra_dir: Path,
    location: PostgresAuthorityLocation,
    host_override: Optional[str] = None,
    port_override: Optional[int] = None,
) -> tuple[str, dict]:
    """Resolve DSN plus redacted evidence from Pulumi outputs + AWS secret."""
    outputs = load_stack_outputs(infra_dir, location)
    endpoint, secret_arn = endpoint_and_secret_arn(outputs, location)
    secret = PostgresSecret.from_json(
        load_secret_string(secret_arn, region=location.region)
    )
    host = host_override or endpoint
    port = port_override or secret.port or DEFAULT_POSTGRES_PORT
    dsn = build_libpq_dsn(
        host=host,
        port=port,
        database=location.database_name,
        secret=secret,
    )
    return dsn, {
        "stack": location.stack,
        "endpoint_output": location.endpoint_output,
        "secret_arn_output": location.secret_arn_output,
        "endpoint": endpoint,
        "database_name": location.database_name,
        "dsn": redacted_dsn(dsn),
    }


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_str(mapping: Mapping[str, Any], key: str) -> Optional[str]:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string when present")
    return value


def _optional_int(mapping: Mapping[str, Any], key: str) -> Optional[int]:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer when present") from exc

